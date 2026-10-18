# The tool-calling loop shared by the agents (think -> call a tool -> observe -> repeat)
# Each agent sets its system prompt and tools and says how a tool call is run. The loop,
# its limits (G10), the retries, the timing of every model call and the log are here, so
# the Support Agent and the Ops Data Agent behave the same way.
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from config import GEMINI_MODEL, PROJECT_ROOT, TEMPERATURE
from src.agents.trace import cost_usd, outcome, result_summary, write_event

MAX_STEPS = 8          # model calls per user message (G10)
MAX_SAME_CALL = 2      # the same tool with the same arguments, at most twice (G10)
MAX_API_RETRIES = 2    # extra attempts when Gemini is busy (503) or a call times out
HTTP_TIMEOUT_S = 60    # one model call may take at most this long, then it counts as failed

API_ERROR_MESSAGE = "Şu anda isteğinizi yanıtlayamıyorum. Lütfen birkaç dakika sonra tekrar deneyin."
# 429: the free Gemini quota is used up. Daily quotas reset at midnight Pacific time,
# which is 10:00 or 11:00 in Turkey depending on US daylight saving time.
QUOTA_MESSAGE = ("Demonun ücretsiz kullanım hakkı şu an dolu. Birkaç dakika sonra tekrar deneyin; "
                 "sorun sürerse günlük hak dolmuş olabilir. Günlük hak her gün Türkiye saatiyle "
                 "sabah 10:00-11:00 civarında yenilenir.")
MAX_STEPS_MESSAGE = "Bu soruyu şu an yanıtlayamadım. İsterseniz talebinizi bir müşteri temsilcisine iletebilirim."
REPEATED_CALL_RESULT = {
    "error": "REPEATED_CALL",
    "message": "You already made this exact call. Answer with the information you have.",
}


@dataclass
class Step:
    tool: str
    args: dict
    result: dict
    latency_s: float = 0.0   # time the tool itself took
    call: int = 0            # index of the model call (in model_calls) that asked for this tool


@dataclass
class AgentReply:
    text: str = ""
    steps: list[Step] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0      # billed as output, counted apart from output_tokens
    stop_reason: str = "answer"   # answer | max_steps | api_error
    latency_s: float = 0.0
    model_calls: list[dict] = field(default_factory=list)   # one entry per model call: time, tokens, error

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.input_tokens, self.output_tokens, self.thinking_tokens)


def make_client() -> genai.Client:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key.")
    # Without a timeout one slow call could hold a turn for minutes (error analysis 8)
    return genai.Client(api_key=api_key,
                        http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_S * 1000))


class ToolAgent:
    """One conversation with a tool-calling agent. Keeps the history between messages."""

    system_prompt: str = ""
    tool_declarations: list = []
    max_steps_message: str = MAX_STEPS_MESSAGE

    def __init__(self, client=None, model: str = GEMINI_MODEL, log_path: Path | None = None):
        self.log_path = log_path   # None: no log (used by the tests)
        self.model = model
        self.client = client or make_client()
        self.history: list[types.Content] = []
        self.last_error: str | None = None
        self.last_error_code: int | None = None   # HTTP code of the last failed call (429: quota)
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=TEMPERATURE,
            tools=[types.Tool(function_declarations=self.tool_declarations)],
            # We run the tools ourselves, so the loop and its limits stay in our code
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # --- what each agent decides ---

    def _run_tool(self, name: str, args: dict) -> dict:
        raise NotImplementedError

    def _start_turn(self, parts: list) -> list:
        """Called before every user message; may add parts to it."""
        return parts

    def _session_label(self) -> str:
        return "-"

    # --- the shared loop ---

    def ask(self, message: str) -> AgentReply:
        """Answer one user message, then write the turn to the log."""
        start_time = time.perf_counter()
        reply = self._run_turn(message)
        reply.latency_s = round(time.perf_counter() - start_time, 2)
        self._log("turn", {
            "model": self.model,
            "message": message,
            "reply": reply.text,
            "steps": [{"tool": s.tool, "args": s.args, "outcome": outcome(s.result), "call": s.call,
                       "latency_s": s.latency_s, "result": result_summary(s.tool, s.result)}
                      for s in reply.steps],
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "thinking_tokens": reply.thinking_tokens,
            "cost_usd": reply.cost_usd,
            "latency_s": reply.latency_s,
            "model_calls": reply.model_calls,
            "stop_reason": reply.stop_reason,
        })
        return reply

    def _run_turn(self, message: str) -> AgentReply:
        reply = AgentReply()
        start = len(self.history)
        parts = self._start_turn([types.Part.from_text(text=message)])
        self.history.append(types.Content(role="user", parts=parts))
        call_counts: dict[tuple, int] = {}

        for _ in range(MAX_STEPS):
            response = self._generate(reply)
            if response is None:
                del self.history[start:]   # forget the failed turn
                message = QUOTA_MESSAGE if self.last_error_code == 429 else API_ERROR_MESSAGE
                reply.text, reply.stop_reason = message, "api_error"
                return reply

            usage = response.usage_metadata
            if usage is not None:
                thinking = getattr(usage, "thoughts_token_count", None) or 0
                reply.input_tokens += usage.prompt_token_count or 0
                reply.output_tokens += usage.candidates_token_count or 0
                reply.thinking_tokens += thinking
                last = reply.model_calls[-1]
                last["input_tokens"] = usage.prompt_token_count or 0
                last["output_tokens"] = usage.candidates_token_count or 0
                last["thinking_tokens"] = thinking
                last["cost_usd"] = cost_usd(last["input_tokens"], last["output_tokens"], thinking)

            candidate = response.candidates[0] if response.candidates else None
            if candidate is None or candidate.content is None:
                del self.history[start:]
                reply.text, reply.stop_reason = API_ERROR_MESSAGE, "api_error"
                return reply

            # Keep the model turn as it is (it may carry thought signatures Gemini needs back)
            self.history.append(candidate.content)

            calls = response.function_calls
            if not calls:   # no tool call: this is the final answer
                reply.text = (response.text or "").strip()
                return reply

            # Run every tool call and send all results back in one turn
            result_parts = []
            for call in calls:
                args = dict(call.args or {})
                key = (call.name, json.dumps(args, sort_keys=True, default=str))
                call_counts[key] = call_counts.get(key, 0) + 1
                tool_start = time.perf_counter()
                if call_counts[key] > MAX_SAME_CALL:
                    result = REPEATED_CALL_RESULT
                else:
                    result = self._run_tool(call.name, args)
                reply.steps.append(Step(call.name, args, result,
                                        latency_s=round(time.perf_counter() - tool_start, 3),
                                        call=len(reply.model_calls) - 1))
                result_parts.append(types.Part.from_function_response(name=call.name, response=result))
            self.history.append(types.Content(role="user", parts=result_parts))

        # Too many steps: close the turn with a safe message
        reply.text, reply.stop_reason = self.max_steps_message, "max_steps"
        self.history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply.text)]))
        return reply

    def _log(self, event: str, data: dict):
        if self.log_path is not None:
            write_event(self.log_path, {"event": event, "session": self._session_label(), **data})

    def _generate(self, reply: AgentReply):
        """Call Gemini and time every call. Retry when it is busy (503), cancels (499) or times out.

        Returns None on failure. Every attempt is recorded in reply.model_calls, so the
        log shows where the time of a slow turn went.
        """
        for attempt in range(MAX_API_RETRIES + 1):
            start = time.perf_counter()
            call = {"latency_s": 0.0, "error": None}
            reply.model_calls.append(call)
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=self.history, config=self.config)
                call["latency_s"] = round(time.perf_counter() - start, 2)
                return response
            except errors.APIError as e:
                self.last_error = f"{e.code}: {e.message}"
                self.last_error_code = e.code
                # 5xx: Gemini is busy. 499: the call was cancelled on the server side (seen in
                # the eval run, error analysis 8). 429 means the quota is used up: no retry.
                retryable = isinstance(e, errors.ServerError) or e.code == 499
            except Exception as e:   # timeout or network error
                self.last_error = f"{type(e).__name__}: {e}"
                self.last_error_code = None
                retryable = True
            call["latency_s"] = round(time.perf_counter() - start, 2)
            call["error"] = self.last_error[:120]
            if not retryable or attempt == MAX_API_RETRIES:
                return None
            time.sleep(5 * (attempt + 1))   # wait 5 s, then 10 s
        return None
