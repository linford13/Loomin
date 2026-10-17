import os
import sqlite3
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from pydantic import BaseModel
from typing import List
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

st.set_page_config(
    page_title="MILO",
    page_icon="📌",
    layout="wide",
    initial_sidebar_state="collapsed"
)

css_rules = [
    "<style>",
    ".stApp { background-color: #0b0f17; color: #f1f5f9; }",
    ".block-container { padding-top: 2rem; max-width: 1200px; }",
    ".milo-logo { font-family: Georgia, serif; font-size: 2.8rem; ",
    "font-weight: 700; color: #ffffff; margin-bottom: 1.5rem; }",
    ".sticky-container { position: relative; background: #fbf7dc; ",
    "color: #27272a; padding: 28px 20px 20px 20px; border-radius: 4px; ",
    "box-shadow: 0 12px 24px rgba(0,0,0,0.45); transform: rotate(-1.5deg); ",
    "min-height: 290px; font-family: cursive, sans-serif; }",
    ".pin { position: absolute; top: -12px; left: 50%; ",
    "transform: translateX(-50%); width: 24px; height: 24px; ",
    "background: radial-gradient(circle at 35% 35%, #ff4b4b, #8a0b0b); ",
    "border-radius: 50%; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }",
    ".sticky-title { font-weight: bold; font-size: 1.05rem; ",
    "border-bottom: 2px dashed #d1c79f; padding-bottom: 6px; ",
    "margin-bottom: 12px; color: #18181b; text-align: center; }",
    ".sticky-item { font-size: 0.88rem; line-height: 1.35; ",
    "margin-bottom: 10px; padding-bottom: 6px; ",
    "border-bottom: 1px dotted #e2d9b5; }",
    ".stTextInput > div > div > input { background-color: #fceee8 !important; ",
    "color: #1a1a1a !important; border-radius: 30px !important; ",
    "padding: 14px 22px !important; border: none !important; }",
    "[data-testid='stForm'] { border: none !important; padding: 0 !important; }",
    "</style>"
]
st.markdown("".join(css_rules), unsafe_allow_html=True)

GEMINI_API_KEY = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    GEMINI_API_KEY = None

if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY is missing from Streamlit Secrets.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "milo_study.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    q1 = (
        "CREATE TABLE IF NOT EXISTS topics ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "subject TEXT, topic TEXT, module TEXT, logged_date TEXT)"
    )
    q2 = (
        "CREATE TABLE IF NOT EXISTS dues ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "subject TEXT, task TEXT, due_date TEXT, "
        "priority TEXT, status TEXT DEFAULT 'Pending')"
    )
    c.execute(q1)
    c.execute(q2)
    conn.commit()
    conn.close()


init_db()


class ExtractedTopic(BaseModel):
    subject: str
    topic: str
    module: str


class ExtractedDue(BaseModel):
    subject: str
    task: str
    due_date: str
    priority: str


class MiloPayload(BaseModel):
    has_academic_content: bool
    assistant_reply: str
    topics: List[ExtractedTopic]
    dues: List[ExtractedDue]


def parse_with_milo(content_items: list):
    today_iso = date.today().isoformat()
    prompt_parts = [
        "Current Date: " + today_iso,
        "You are MILO, an academic tracker for a college student.",
        "Extract topics taught and upcoming dues from notes or files.",
        "Use 'General' if module is unknown.",
        "Convert relative dates (like tomorrow or Friday) to YYYY-MM-DD.",
        "Use 'TBD' if due_date is unknown, and 'Normal' or 'High' for priority.",
        "If input is casual chat, set has_academic_content=False ",
        "and write a friendly response in assistant_reply."
    ]
    sys_prompt = "\n".join(prompt_parts)
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[sys_prompt] + content_items,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MiloPayload
            )
        )
        if response.parsed:
            return response.parsed
        return MiloPayload.model_validate_json(response.text)
    except Exception as e:
        st.error("MILO engine error: " + str(e))
        return None


st.markdown("<div class='milo-logo'>MILO</div>", unsafe_allow_html=True)

with st.container():
    with st.form("milo_chat_form", clear_on_submit=True):
        f_col1, f_col2 = st.columns([10, 2])
        with f_col1:
            chat_text = st.text_input(
                "Chat Input",
                placeholder="Ask MILO, paste lecture updates, or drop dues...",
                label_visibility="collapsed"
            )
        with f_col2:
            submit_btn = st.form_submit_button(
                "Send",
                use_container_width=True
            )
        with st.expander("+ Attach Files (Photos, Syllabus PDFs, Notes)"):
            uploaded_files = st.file_uploader(
                "Upload files",
                type=["png", "jpg", "jpeg", "pdf", "txt"],
                accept_multiple_files=True,
                label_visibility="collapsed"
            )

if submit_btn and (chat_text.strip() or uploaded_files):
    payload_items = []
    if chat_text.strip():
        payload_items.append("Notes:\n" + chat_text)
    if uploaded_files:
        for f in uploaded_files:
            if "image" in f.type:
                payload_items.append(Image.open(f))
            elif "pdf" in f.type:
                reader = PdfReader(f)
                pages = [p.extract_text() or "" for p in reader.pages[:10]]
                txt = "\n".join(pages)
                payload_items.append("PDF (" + f.name + "):\n" + txt[:6000])
            elif "text" in f.type:
                raw_txt = f.read().decode("utf-8")[:6000]
                payload_items.append("Text (" + f.name + "):\n" + raw_txt)

    with st.spinner("MILO is parsing..."):
        res = parse_with_milo(payload_items)
        if res is not None:
            if not res.has_academic_content:
                reply = res.assistant_reply
                if not reply:
                    reply = "Hey! Send me your class updates or dues."
                st.info(reply)
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                q_ins_t = (
                    "INSERT INTO topics "
                    "(subject, topic, module, logged_date) "
                    "VALUES (?, ?, ?, ?)"
                )
                for t in res.topics:
                    mod_val = t.module if t.module else "General"
                    c.execute(
                        q_ins_t,
                        (t.subject, t.topic, mod_val, str(date.today()))
                    )
                q_ins_d = (
                    "INSERT INTO dues "
                    "(subject, task, due_date, priority, status) "
                    "VALUES (?, ?, ?, ?, 'Pending')"
                )
                for d in res.dues:
                    due_val = d.due_date if d.due_date else "TBD"
                    prio_val = d.priority if d.priority else "Normal"
                    c.execute(
                        q_ins_d,
                        (d.subject, d.task, due_val, prio_val)
                    )
                conn.commit()
                conn.close()
                st.rerun()

st.write("")
st.write("")

col_left, col_right = st.columns([1, 2], gap="large")
conn = sqlite3.connect(DB_FILE)

with col_left:
    q_dues = (
        "SELECT id, subject, task, due_date FROM dues "
        "WHERE status = 'Pending' ORDER BY due_date ASC LIMIT 5"
    )
    dues = pd.read_sql_query(q_dues, conn)

    items_list = []
    if dues.empty:
        empty_note = (
            "<div style='text-align:center; padding-top:40px; "
            "color:#52525b;'>No dues pending!<br>Enjoy your day</div>"
        )
        items_list.append(empty_note)
    else:
        for _, row in dues.iterrows():
            s_subj = str(row["subject"])
            s_task = str(row["task"])
            s_due = str(row["due_date"])
            item_html = (
                "<div class='sticky-item'>"
                + "<strong>[" + s_subj + "]</strong> " + s_task + "<br>"
                + "<span style='color: #dc2626;'>Due: " + s_due + "</span>"
                + "</div>"
            )
            items_list.append(item_html)

    sticky_html = (
        "<div class='sticky-container'>"
        + "<div class='pin'></div>"
        + "<div class='sticky-title'>UPCOMING DUES</div>"
        + "".join(items_list)
        + "</div>"
    )
    st.markdown(sticky_html, unsafe_allow_html=True)

    if not dues.empty:
        with st.expander("Mark a Due Complete"):
            for _, r in dues.iterrows():
                row_id = int(r["id"])
                lbl = "Done: " + str(r["subject"]) + " - " + str(r["task"])[:16]
                if st.button(lbl, key="done_" + str(row_id), use_container_width=True):
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE dues
