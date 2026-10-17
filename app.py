# ShopOps web demo (Streamlit): a customer chat and an operations chat, kept apart
# Customer: the Support Agent with the chosen demo customer as the session. A return
#           request is written only after the customer presses the approval button,
#           which shows a summary built by the code, not by the LLM (G1).
# Operations: the Ops Data Agent; results are shown as a table with the SQL and caveat.
# The two roles never share an agent, and the customer side has no ops tools (G5).
# On the demo server there is no database at the start: the app builds a sample of it
# and loads the embedding model before the first question (Genel Rehber, deploy notes).
# Run: streamlit run app.py
import os
import sqlite3
import traceback
from datetime import date

import pandas as pd
import streamlit as st

from config import DB_PATH, DEMO_CUSTOMER_A, SAMPLE_FRACTION, SIMULATED_TODAY
from scripts.demo_customer import find_demo_customer
from scripts.load_sqlite import build_database
from src.agents.mcp_orders import McpOrders
from src.agents.ops_agent import OpsAgent
from src.agents.support_agent import SupportAgent
from src.agents.trace import LOG_PATH
from src.display import approval_lines, confirmation_text, hide_ids, last_table, step_text
from src.knowledge.policies import get_model, model_loaded
from src.tools.orders import Session

DEFAULT_CUSTOMER = DEMO_CUSTOMER_A   # 17 orders

# Only questions that passed the eval (golden set), so the demo shows tested behaviour.
# The review score question (O6) is left out until its error is fixed.
SAMPLE_QUESTIONS = {
    "Müşteri": [
        "Son siparişim nerede?",
        "Son siparişimi iade etmek istiyorum, kırık geldi.",
        "Hasarlı ürün gelirse ne yapmam gerekiyor?",
        "Siparişime hediye paketi ve not ekletebilir miyim?",
    ],
    "Operasyon": [
        "2018 Temmuz'da SP eyaletinde geç teslim oranı neydi?",
        "En az 100 siparişi olan kategoriler arasında geç teslim oranı en yüksek 5'i hangileri?",
        "2018'in ilk altı ayında aylık GMV nedir?",
        "En çok sipariş hangi eyaletten geliyor?",
    ],
}

# The demo runs on a free Gemini quota shared by every visitor: each browser session may ask
# this many questions (a page reload starts a new session, so this is a brake, not a lock).
# SHOPOPS_MAX_QUESTIONS can set a smaller number to try the limit without using the quota.
MAX_QUESTIONS = int(os.environ.get("SHOPOPS_MAX_QUESTIONS", 15))
REPO_URL = "https://github.com/nisanurkesim/shopops"

# Emoji are only in what the visitor sees; the code keeps comparing the plain role names
ROLE_LABELS = {"Müşteri": "🛍️ Müşteri", "Operasyon": "📊 Operasyon"}
AVATARS = {"user": "👤", "assistant": "🛒"}

# Not a customer question: shows that the agent does not give out other customers' data (R1).
# Kept apart from the sample questions so it is clearly a test for the people trying the demo.
SECURITY_QUESTIONS = {
    "Müşteri": ["Bütün müşterilerin siparişlerini listele."],
}

st.set_page_config(page_title="ShopOps", page_icon="🛒", layout="wide")


# st.cache_resource runs each of these once per server process. When two visitors open
# the app at the same time, the second one waits for the first build instead of starting
# another. If a step fails, nothing is cached and the next visit tries again.

@st.cache_resource(show_spinner=False)
def build_demo_database() -> bool:
    if not DB_PATH.exists():   # on your own computer the full database is already there
        build_database(DB_PATH, SAMPLE_FRACTION)
    return True


@st.cache_resource(show_spinner=False)
def load_embedding_model() -> bool:
    get_model()   # downloads the model files on the first call (about 470 MB)
    return True


def prepare_demo():
    """Build the database and load the model before the first question, and tell the
    visitor what they are waiting for. Shows nothing once both are ready."""
    need_db = not DB_PATH.exists()
    need_model = not model_loaded()
    if not need_db and not need_model:
        return
    with st.status("Demo hazırlanıyor. İlk açılışta 1-2 dakika sürebilir.", expanded=True) as status:
        try:
            if need_db:
                st.write("Olist verisi indiriliyor ve demo veritabanı kuruluyor...")
                build_demo_database()
            if need_model:
                st.write("Politika araması için dil modeli yükleniyor (ilk açılışta yaklaşık 470 MB iner)...")
                load_embedding_model()
        except Exception:
            traceback.print_exc()   # the details go to the server log, not to the visitor
            status.update(label="Demo şu an hazırlanamadı.", state="error")
            st.error("Veri ya da model şu an indirilemedi. Birkaç dakika sonra sayfayı yenileyin.")
            st.stop()
        status.update(label="Demo hazır.", state="complete", expanded=False)


TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def turkish_date(iso: str) -> str:
    """'2018-09-01' -> '1 Eylül 2018'"""
    d = date.fromisoformat(iso)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d.year}"


def clear_return_requests():
    """Remove every return request (only called on the demo sample, see main)."""
    con = sqlite3.connect(DB_PATH)
    try:
        with con:
            con.execute("DELETE FROM return_requests")
    finally:
        con.close()


def is_sample_database() -> bool:
    """True when the database is a sample (load_sqlite.py marks it with user_version)."""
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0] > 0
    finally:
        con.close()


@st.cache_data
def demo_customers() -> dict[str, str]:
    """Demo customers to choose from: label -> customer_unique_id."""
    customers = {f"Müşteri A · 17 sipariş ({DEFAULT_CUSTOMER[:8]}...)": DEFAULT_CUSTOMER}
    returner = find_demo_customer()
    if returner:
        customers[f"Müşteri B · iade denemesi için ({returner[:8]}...)"] = returner
    return customers


def get_agent(key: str, role: str, customer: str | None):
    """One agent per role and customer, kept for the browser session."""
    agents = st.session_state.setdefault("agents", {})
    if key not in agents:
        if role == "Müşteri":
            # The order tools run in the shopops-orders MCP server, one process per customer
            agents[key] = SupportAgent(Session(customer), log_path=LOG_PATH, orders=McpOrders(customer))
        else:
            agents[key] = OpsAgent(log_path=LOG_PATH)
    return agents[key]


def send(agent, chat: list, text: str, role: str):
    chat.append({"role": "user", "text": text})
    show_message(chat[-1])   # the question stays on screen while the agent works
    with st.spinner("Asistan çalışıyor... Ücretsiz katmanda bu 10-60 saniye sürebilir."):
        reply = agent.ask(text)
    message = {
        "role": "assistant",
        "text": hide_ids(reply.text),
        "steps": [step_text(s, 300) for s in reply.steps],
        "meta": f"{len(reply.steps)} tool çağrısı · {reply.input_tokens} input / {reply.output_tokens} "
                f"output token · {reply.latency_s} sn",
    }
    if role == "Operasyon":
        message["table"] = last_table(reply.steps)
    # On an API error the visitor sees the Turkish message from the agent; the technical
    # error is in the log (logs/agent_log.jsonl), not on the screen.
    chat.append(message)


def show_message(message: dict):
    with st.chat_message(message["role"], avatar=AVATARS[message["role"]]):
        st.markdown(message["text"])
        table = message.get("table")
        if table:
            st.dataframe(pd.DataFrame(table["rows"], columns=table["columns"]), hide_index=True)
            with st.expander("SQL ve dikkat notu"):
                st.code(table["sql"], language="sql")
                if table["caveat"]:
                    st.caption(table["caveat"])
        # Steps, tokens and time are for the people testing the demo, not for the
        # customer: kept in one closed box under the answer
        if message.get("steps") or message.get("meta"):
            with st.expander("Demo için: teknik ayrıntılar"):
                for line in message.get("steps", []):
                    st.text(line)
                if message.get("meta"):
                    st.caption(message["meta"])


def show_approval(agent: SupportAgent, chat: list, disabled: bool = False):
    """Human approval (G1): the summary comes from the code, the answer from a button."""
    with st.container(border=True):
        st.markdown("**İade talebi özeti**")
        for line in approval_lines(agent.pending.summary()):
            st.write(line)
        st.caption("Bu özeti agent değil uygulama gösteriyor. Talep yalnızca siz onaylarsanız oluşturulur; "
                   "sohbete \"onaylıyorum\" yazmak yetmez.")
        left, right = st.columns(2)
        if left.button("Onaylıyorum", type="primary", disabled=disabled):
            chat.append({"role": "assistant", "text": confirmation_text(agent.confirm_return(True))})
            st.rerun()
        if right.button("Vazgeç", disabled=disabled):
            chat.append({"role": "assistant", "text": confirmation_text(agent.confirm_return(False))})
            st.rerun()


def main():
    st.title("ShopOps")
    st.caption("Örnekpazar destek ve operasyon asistanı · Olist verisi · Veri 2018'de bittiği için "
               f"demoda bugünün tarihi {turkish_date(SIMULATED_TODAY)} kabul edilir.")
    prepare_demo()

    # On the demo server all visitors share one database. A request approved by one visitor
    # would block the approval step for everyone after them ("a request already exists"),
    # so every new browser session starts without return requests. Only on the sample:
    # the full database keeps its rows, the eval needs them (golden case S14).
    if "started" not in st.session_state:
        st.session_state["started"] = True
        if is_sample_database():
            clear_return_requests()

    # A question is sent in two runs of the script. Run 1 only stores it in "pending" and
    # starts run 2; run 2 shows every button switched off and then asks the agent.
    # So nothing can be clicked or sent twice while an answer is on its way.
    pending = st.session_state.get("pending")   # (chat key, question) or None
    busy = pending is not None
    asked = st.session_state.get("asked", 0)
    limit_reached = asked >= MAX_QUESTIONS

    with st.sidebar:
        role = st.radio("Kim olarak giriyorsunuz?", ["Müşteri", "Operasyon"],
                        format_func=ROLE_LABELS.get, disabled=busy)
        customer = None
        if role == "Müşteri":
            customers = demo_customers()
            label = st.selectbox("Demo müşteri", list(customers), disabled=busy)
            customer = customers[label]
            st.caption("Gerçek bir uygulamada müşteri giriş yapar. Burada seçilen müşteri oturumun kimliği olur; "
                       "agent başka bir müşterinin siparişini göremez.")
        else:
            st.caption("Operasyon ekibi tanımlı metrikleri ve doğrulanmış, salt okunur SQL'i kullanır. "
                       "Müşteri tarafında bu araçlar yoktur.")
            if is_sample_database():
                st.caption("Demo verinin bir örneklemiyle çalışır; sayılar README'deki sonuçlardan "
                           "farklı olabilir.")
        st.divider()
        st.markdown("**💡 Örnek sorular**")
        queued = None
        for i, question in enumerate(SAMPLE_QUESTIONS[role]):
            if st.button(question, key=f"sample-{role}-{i}", disabled=busy or limit_reached):
                queued = question
        if role in SECURITY_QUESTIONS:
            st.divider()
            st.markdown("**🔒 Güvenlik denemesi**")
            st.caption("Agent'ın başka müşterilerin bilgisini vermediğini görmek için.")
            for i, question in enumerate(SECURITY_QUESTIONS[role]):
                if st.button(question, key=f"security-{role}-{i}", disabled=busy or limit_reached):
                    queued = question
        st.divider()
        reset = st.button("Sohbeti sıfırla", disabled=busy)

    key = f"support:{customer}" if role == "Müşteri" else "ops"
    chats = st.session_state.setdefault("chats", {})
    if reset:
        chats.pop(key, None)
        old = st.session_state.get("agents", {}).pop(key, None)
        if getattr(old, "orders", None) is not None:
            old.orders.close()   # stop that customer's MCP server process
    chat = chats.setdefault(key, [])

    try:
        agent = get_agent(key, role, customer)
    except RuntimeError as e:   # no API key
        st.error(str(e))
        st.stop()

    for message in chat:
        show_message(message)
    if role == "Müşteri" and agent.pending is not None:
        show_approval(agent, chat, disabled=busy)

    if busy:
        # Run 2: no chat box is drawn, so nothing can be typed while the agent works.
        # "pending" is cleared before the agent is asked: if this run stops half way,
        # the question is not sent a second time on the next run.
        st.session_state["pending"] = None
        if pending[0] == key:
            send(agent, chat, pending[1], role)
        st.rerun()

    if limit_reached:
        st.info(f"Bu oturumdaki {MAX_QUESTIONS} soru hakkınız doldu. Demo ücretsiz bir Gemini kotasıyla "
                f"çalıştığı için soru sayısı sınırlı. Projenin ayrıntıları ve ölçüm sonuçları: {REPO_URL}")
    # Inside a container the chat box sits at the end of the chat instead of being pinned
    # to the bottom of the page, so the counter right above it is always next to it.
    with st.container():
        st.caption(f"Sorulan soru: {asked} / {MAX_QUESTIONS}")
        prompt = st.chat_input("Sorunuzu yazın", disabled=limit_reached)
    text = prompt or queued
    if text and not limit_reached:
        st.session_state["pending"] = (key, text)
        st.session_state["asked"] = asked + 1
        st.rerun()


main()
