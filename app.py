import os
import sqlite3
from datetime import date
import pandas as pd
import streamlit as st
from pydantic import BaseModel
from typing import List, Optional
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

# ----------------- Configuration & DB -----------------
st.set_page_config(page_title="Academic Work & Dues Tracker", page_icon="🎓", layout="wide")

# Read API Key from st.secrets first, then fall back to os.environ
GEMINI_API_KEY = None
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    st.error("⚠️ GEMINI_API_KEY is not configured! Please add it to your Streamlit Cloud Secrets.")
    st.stop()

ai_client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "study_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            summary TEXT,
            logged_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS dues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            task TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ----------------- AI Parser Schema -----------------
class ExtractedTopic(BaseModel):
    subject: str
    summary: str

class ExtractedDue(BaseModel):
    subject: str
    task: str
    due_date: Optional[str]

class AcademicPayload(BaseModel):
    topics: List[ExtractedTopic]
    dues: List[ExtractedDue]

def parse_with_ai(content_items: list) -> Optional[AcademicPayload]:
    system_instruction = f"""
    Current Date: {date.today().isoformat()}
    Analyze the student's note and attached documents/images.
    1. Extract the main topics covered or actively ongoing.
    2. Extract any upcoming deadlines, assignments, submissions, or dues.
    If a due date is relative (e.g., 'next Monday', 'tomorrow'), resolve it into YYYY-MM-DD format using current date.
    """
    
    contents = [system_instruction] + content_items

    # Fallback cascade to prevent ClientError
    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]
    
    for model_name in models_to_try:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AcademicPayload
                )
            )
            return AcademicPayload.model_validate_json(response.text)
        except Exception as e:
            if model_name == models_to_try[-1]:
                st.error(f"API Error ({model_name}): {e}")
                return None
            continue

# ----------------- UI Layout -----------------
st.title("🎓 Academic Work & Dues Tracker")

with st.expander("📝 Log Notes, Blackboard Snaps, or Circular PDFs", expanded=True):
    user_input = st.text_area(
        "Dump your raw notes or class updates here (optional if uploading files):",
        placeholder="e.g., Covered module 1 in Physics. Lab record due Friday."
    )
    
    uploaded_files = st.file_uploader(
        "Or upload images / circular PDFs / text documents (multiple allowed):",
        type=["png", "jpg", "jpeg", "pdf", "txt"],
        accept_multiple_files=True
    )
    
    if st.button("Analyze & Log", type="primary"):
        content_items = []
        
        if user_input.strip():
            content_items.append(f"Student Notes:\n{user_input}")
            
        if uploaded_files:
            for file in uploaded_files:
                file_type = file.type
                
                # Image processing
                if "image" in file_type:
                    img = Image.open(file)
                    content_items.append(img)
                    
                # PDF processing
                elif "pdf" in file_type:
                    reader = PdfReader(file)
                    extracted_pages = []
                    for page in reader.pages[:10]:
                        txt = page.extract_text()
                        if txt:
                            extracted_pages.append(txt)
                    pdf_text = "\n".join(extracted_pages)
                    content_items.append(f"PDF ({file.name}):\n{pdf_text[:6000]}")
                    
                # Plain Text processing
                elif "text" in file_type:
                    text_content = file.read().decode("utf-8")
                    content_items.append(f"File ({file.name}):\n{text_content[:6000]}")

        if not content_items:
            st.warning("Please type some notes or upload at least one file first.")
        else:
            with st.spinner("Gemini is reading all files and extracting your tasks..."):
                extracted = parse_with_ai(content_items)
                
                if extracted:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    
                    for t in extracted.topics:
                        c.execute(
                            "INSERT INTO topics (subject, summary, logged_date) VALUES (?, ?, ?)",
                            (t.subject, t.summary, str(date.today()))
                        )
                        
                    for d in extracted.dues:
                        c.execute(
                            "INSERT INTO dues (subject, task, due_date, status) VALUES (?, ?, ?, 'Pending')",
                            (d.subject, d.task, d.due_date if d.due_date else "TBD")
                        )
                        
                    conn.commit()
                    conn.close()
                    st.success("Successfully logged topics and upcoming dues!")
                    st.rerun()

st.divider()

# ----------------- Dashboard View -----------------
col1, col2 = st.columns([1, 1])
conn = sqlite3.connect(DB_FILE)

with col1:
    st.subheader("⏳ Action Items & Pending Dues")
    dues_df = pd.read_sql_query("SELECT id, subject, task, due_date, status FROM dues WHERE status = 'Pending' ORDER BY due_date ASC", conn)
    
    if dues_df.empty:
        st.info("No pending tasks! All clear.")
    else:
        for _, row in dues_df.iterrows():
            d_col1, d_col2 = st.columns([4, 1])
            with d_col1:
                st.markdown(f"**[{row['subject']}]** {row['task']}  \n📅 `Due: {row['due_date']}`")
            with d_col2:
                if st.button("Done", key=f"done_{row['id']}"):
                    c = conn.cursor()
                    c.execute("UPDATE dues SET status = 'Completed' WHERE id = ?", (row['id'],))
                    conn.commit()
                    st.rerun()
            st.write("---")

with col2:
    st.subheader("📚 Syllabus Covered (Recent)")
    topics_df = pd.read_sql_query("SELECT subject, summary, logged_date FROM topics ORDER BY logged_date DESC LIMIT 10", conn)
    
    if topics_df.empty:
        st.info("No lecture topics logged yet.")
    else:
        st.dataframe(topics_df, use_container_width=True, hide_index=True)

# ----------------- Summarizer Reports -----------------
st.divider()
st.subheader("📊 Generate Summary Reports")
rep_col1, rep_col2 = st.columns(2)

with rep_col1:
    if st.button("Generate Daily Digest"):
        daily_topics = pd.read_sql_query("SELECT subject, summary FROM topics WHERE logged_date = ?", conn, params=(str(date.today()),))
        daily_dues = pd.read_sql_query("SELECT subject, task, due_date FROM dues WHERE status = 'Pending'", conn)
        
        st.markdown(f"### 📘 Daily Recap — {date.today().isoformat()}")
        if daily_topics.empty:
            st.write("No new topics logged today.")
        else:
            st.markdown("**Topics Covered:**")
            for _, r in daily_topics.iterrows():
                st.markdown(f"- **{r['subject']}**: {r['summary']}")
        
        st.markdown("**Active Dues:**")
        for _, r in daily_dues.iterrows():
            st.markdown(f"- ⚠️ **{r['subject']}**: {r['task']} (Due: `{r['due_date']}`)")

with rep_col2:
    if st.button("Generate Weekly Roll-Up"):
        all_topics = pd.read_sql_query("SELECT subject, summary, logged_date FROM topics ORDER BY logged_date DESC LIMIT 15", conn)
        st.markdown("### 🗓️ Weekly Academic Overview")
        if all_topics.empty:
            st.write("No topics logged this week.")
        else:
            for _, r in all_topics.iterrows():
                st.markdown(f"- `{r['logged_date']}` **[{r['subject']}]**: {r['summary']}")

conn.close()
