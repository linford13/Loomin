import os
import sqlite3
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from pydantic import BaseModel, Field
from typing import List, Optional
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

# ----------------- App Config & Visual Styling -----------------
st.set_page_config(
    page_title="MILO",
    page_icon="📌",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    /* Dark Canvas */
    .stApp {
        background-color: #0b0f17;
        color: #f1f5f9;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }

    /* Brand Logo */
    .milo-logo {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: 2.8rem;
        font-weight: 700;
        letter-spacing: 2px;
        color: #ffffff;
        margin-bottom: 1.5rem;
    }

    /* Sticky Note Styling */
    .sticky-container {
        position: relative;
        background: #fbf7dc;
        color: #27272a;
        padding: 28px 20px 20px 20px;
        border-radius: 4px;
        box-shadow: 0 12px 24px rgba(0,0,0,0.45), 0 4px 6px rgba(0,0,0,0.3);
        transform: rotate(-1.5deg);
        min-height: 290px;
        font-family: 'Comic Sans MS', 'Segoe Print', cursive, sans-serif;
    }
    .pin {
        position: absolute;
        top: -12px;
        left: 50%;
        transform: translateX(-50%);
        width: 24px;
        height: 24px;
        background: radial-gradient(circle at 35% 35%, #ff4b4b, #8a0b0b);
        border-radius: 50%;
        box-shadow: 0 4px 8px rgba(0,0,0,0.5);
    }
    .sticky-title {
        font-weight: bold;
        font-size: 1.05rem;
        border-bottom: 2px dashed #d1c79f;
        padding-bottom: 6px;
        margin-bottom: 12px;
        color: #18181b;
        text-align: center;
    }
    .sticky-item {
        font-size: 0.88rem;
        line-height: 1.35;
        margin-bottom: 10px;
        padding-bottom: 6px;
        border-bottom: 1px dotted #e2d9b5;
    }

    /* Chat bubble aesthetic */
    .stTextInput > div > div > input {
        background-color: #fceee8 !important;
        color: #1a1a1a !important;
        border-radius: 30px !important;
        padding: 14px 22px !important;
        border: none !important;
        font-size: 1rem !important;
    }
    
    [data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- Secrets & Gemini Client -----------------
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    st.error("⚠️ GEMINI_API_KEY is missing from Streamlit Secrets.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "milo_study.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            topic TEXT,
            module TEXT,
            logged_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS dues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            task TEXT,
            due_date TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ----------------- Structured AI Parser Schema -----------------
class ExtractedTopic(BaseModel):
    subject: str = Field(description="Normalized subject title (e.g. Physics, Math, CSE)")
    topic: str = Field(description="Summary of concept covered")
    module: Optional[str] = Field(default="General", description="Module/Unit if mentioned")

class ExtractedDue(BaseModel):
    subject: str
    task: str
    due_date: Optional[str] = Field(default="TBD", description="Resolved ISO date YYYY-MM-DD")
    priority: str = Field(default="Normal")

class MiloPayload(BaseModel):
    has_academic_content: bool
    assistant_reply: Optional[str] = ""
    topics: List[ExtractedTopic] = Field(default_factory=list)
    dues: List[ExtractedDue] = Field(default_factory=list)

def parse_with_milo(content_items: list) -> Optional[MiloPayload]:
    system_instruction = f"""
    Current Date: {date.today().isoformat()}
    You are MILO, an academic tracker for a student.
    Extract topics taught and upcoming dues/submissions from raw notes or files.
    Convert relative dates ('due Friday', 'tomorrow') to YYYY-MM-DD.
    If input is conversational/greeting, set has_academic_content=False with a brief greeting in assistant_reply.
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[system_instruction] + content_items,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MiloPayload
            )
        )
        if response.parsed:
            return response.parsed
        return MiloPayload.model_validate_json(response.text)
    except Exception as e:
        st.error(f"MILO engine error: {e}")
        return None

# ----------------- Top Header -----------------
st.markdown("<div class='milo-logo'>MILO</div>", unsafe_allow_html=True)

# ----------------- Chat Bar with (+) File Drawer -----------------
with st.container():
    with st.form("milo_chat_form", clear_on_submit=True):
        f_col1, f_col2 = st.columns([11, 1])
        with f_col1:
            chat_text = st.text_input(
                "Chat Input", 
                placeholder="Ask MILO, paste lecture updates, or drop deadlines...",
                label_visibility="collapsed"
            )
        with f_col2:
            submit_btn = st.form_submit_button("Send", use_container_width=True)

    with st.expander("➕ Attach Files (Blackboard photos, Syllabus PDFs, Note docs)"):
        uploaded_files = st.file_uploader(
            "Upload files",
            type=["png", "jpg", "jpeg", "pdf", "txt"],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )

# Process Input
if submit_btn and (chat_text.strip() or uploaded_files):
    payload_items = []
    if chat_text.strip():
        payload_items.append(f"Notes:\n{chat_text}")
    if uploaded_files:
        for f in uploaded_files:
            if "image" in f.type:
                payload_items.append(Image.open(f))
            elif "pdf" in f.type:
                reader = PdfReader(f)
                txt = "\n".join([page.extract_text() or "" for page in reader.pages[:10]])
                payload_items.append(f"PDF ({f.name}):\n{txt[:6000]}")
            elif "text" in f.type:
                payload_items.append(f"Text ({f.name}):\n{f.read().decode('utf-8')[:6000]}")

    with st.spinner("MILO is parsing..."):
        res = parse_with_milo(payload_items)
        if res:
            if not res.has_academic_content:
                st.info(res.assistant_reply or "👋 Hey! Send me what you covered in class or upcoming dues to pin them down.")
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                for t in res.topics:
                    c.execute("INSERT INTO topics (subject, topic, module, logged_date) VALUES (?, ?, ?, ?)",
                              (t.subject, t.topic, t.module or "General", str(date.today())))
                for d in res.dues:
                    c.execute("INSERT INTO dues (subject, task, due_date, priority, status) VALUES (?, ?, ?, ?, 'Pending')",
                              (d.subject, d.task, d.due_date or "TBD", d.priority or "Normal"))
                conn.commit()
                conn.close()
                st.rerun()

st.write("")
st.write("")

# ----------------- Main Display -----------------
col_left, col_right = st.columns([1, 2], gap="large")
conn = sqlite3.connect(DB_FILE)

# LEFT COLUMN: Sticky Note (Dues & Deadlines)
with col_left:
    dues = pd.read_sql_query(
        "SELECT id, subject, task, due_date FROM dues WHERE status = 'Pending' ORDER BY due_date ASC LIMIT 5", 
        conn
    )
    
    items_html = ""
    if dues.empty:
        items_html = "<div style='text-align:center; padding-top:40px; color:#52525b;'>No dues pending!<br>Enjoy your day ✨</div>"
    else:
        for _, row in dues.iterrows():
            items_html += (
                "<div class='sticky-item'>"
                f"<strong>[{row['subject']}]</strong> {row['task']}<br>"
                f"<span style='color: #dc2
