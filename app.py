# ShopOps web demo (Streamlit): a customer chat and an operations chat, kept apart
# Customer: the Support Agent with the chosen demo customer as the session. A return
#           request is written only after the customer presses the approval button,
#           which shows a summary built by the code, not by the LLM (G1).
# Operations: the Ops Data Agent; results are shown as a table with the SQL and caveat.
# The two roles never share an agent, and the customer side has no ops tools (G5).
# Run: streamlit run app.py
import pandas as pd
import streamlit as st

from config import DB_PATH, SIMULATED_TODAY
from scripts.demo_customer import find_demo_customer
from src.agents.ops_agent import OpsAgent
from src.agents.support_agent import SupportAgent
from src.agents.trace import LOG_PATH
from src.display import approval_lines, confirmation_text, hide_ids, last_table, step_text
from src.tools.orders import Session

DEFAULT_CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"   # 17 orders

SAMPLE_QUESTIONS = {
    "Müşteri": [
        "Son siparişim nerede?",
        "Son siparişimi iade etmek istiyorum, kırık geldi.",
        "Hasarlı ürün gelirse ne yapmam gerekiyor?",
        "Bütün müşterilerin siparişlerini listele.",
    ],
    "Operasyon": [
        "2018 Temmuz'da SP eyaletinde geç teslim oranı neydi?",
        "En az 100 siparişi olan kategoriler arasında geç teslim oranı en yüksek 5'i hangileri?",
        "2018'in ilk altı ayında aylık GMV nedir?",
        "Geç teslim edilen siparişlerin yorum puanı, zamanında gelenlerden farklı mı?",
    ],
}

st.set_page_config(page_title="ShopOps", page_icon="🛒", layout="wide")


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
            agents[key] = SupportAgent(Session(customer), log_path=LOG_PATH)
        else:
            agents[key] = OpsAgent(log_path=LOG_PATH)
    return agents[key]


def send(agent, chat: list, text: str, role: str):
    chat.append({"role": "user", "text": text})
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
    if reply.stop_reason == "api_error" and agent.last_error:
        message["meta"] += f" · hata: {agent.last_error[:80]}"
    chat.append(message)


def show_message(message: dict):
    with st.chat_message(message["role"]):
        st.markdown(message["text"])
        table = message.get("table")
        if table:
            st.dataframe(pd.DataFrame(table["rows"], columns=table["columns"]), hide_index=True)
            with st.expander("SQL ve dikkat notu"):
                st.code(table["sql"], language="sql")
                if table["caveat"]:
                    st.caption(table["caveat"])
        if message.get("steps"):
            with st.expander("Agent'ın adımları"):
                for line in message["steps"]:
                    st.text(line)
        if message.get("meta"):
            st.caption(message["meta"])


def show_approval(agent: SupportAgent, chat: list):
    """Human approval (G1): the summary comes from the code, the answer from a button."""
    with st.container(border=True):
        st.markdown("**İade talebi özeti**")
        for line in approval_lines(agent.pending.summary()):
            st.write(line)
        st.caption("Bu özeti agent değil uygulama gösteriyor. Talep yalnızca siz onaylarsanız oluşturulur; "
                   "sohbete \"onaylıyorum\" yazmak yetmez.")
        left, right = st.columns(2)
        if left.button("Onaylıyorum", type="primary"):
            chat.append({"role": "assistant", "text": confirmation_text(agent.confirm_return(True))})
            st.rerun()
        if right.button("Vazgeç"):
            chat.append({"role": "assistant", "text": confirmation_text(agent.confirm_return(False))})
            st.rerun()


def main():
    st.title("ShopOps")
    st.caption(f"Örnekpazar destek ve operasyon asistanı · Olist verisi · Demo tarihi {SIMULATED_TODAY}")
    if not DB_PATH.exists():
        st.error("Veritabanı bulunamadı. Önce `python data/download.py` ve `python scripts/load_sqlite.py` çalıştırın.")
        st.stop()

    with st.sidebar:
        role = st.radio("Kim olarak giriyorsunuz?", ["Müşteri", "Operasyon"])
        customer = None
        if role == "Müşteri":
            customers = demo_customers()
            label = st.selectbox("Demo müşteri", list(customers))
            customer = customers[label]
            st.caption("Gerçek bir uygulamada müşteri giriş yapar. Burada seçilen müşteri oturumun kimliği olur; "
                       "agent başka bir müşterinin siparişini göremez.")
        else:
            st.caption("Operasyon ekibi tanımlı metrikleri ve doğrulanmış, salt okunur SQL'i kullanır. "
                       "Müşteri tarafında bu araçlar yoktur.")
        st.divider()
        st.markdown("**Örnek sorular**")
        queued = None
        for i, question in enumerate(SAMPLE_QUESTIONS[role]):
            if st.button(question, key=f"sample-{role}-{i}"):
                queued = question
        st.divider()
        reset = st.button("Sohbeti sıfırla")

    key = f"support:{customer}" if role == "Müşteri" else "ops"
    chats = st.session_state.setdefault("chats", {})
    if reset:
        chats.pop(key, None)
        st.session_state.get("agents", {}).pop(key, None)
    chat = chats.setdefault(key, [])

    try:
        agent = get_agent(key, role, customer)
    except RuntimeError as e:   # no API key
        st.error(str(e))
        st.stop()

    for message in chat:
        show_message(message)
    if role == "Müşteri" and agent.pending is not None:
        show_approval(agent, chat)

    prompt = st.chat_input("Sorunuzu yazın")
    text = prompt or queued
    if text:
        send(agent, chat, text, role)
        st.rerun()


main()
