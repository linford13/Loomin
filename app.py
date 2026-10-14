import os
import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st
from pydantic import BaseModel
from typing import List, Optional
from google import genai
from google.genai import types

# ----------------- Configuration & DB -----------------
st.set_page_config(page_title="Academic Co-Pilot", page_icon="🎓", layout="wide")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    st.error("Please set the GEMINI_API_KEY environment variable.")
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
    due_date: Optional[str]  # Format: YYYY-MM-DD

class AcademicPayload(BaseModel):
    topics: List[ExtractedTopic]
    dues: List[ExtractedDue]

def parse_with_ai(raw_text: str) -> AcademicPayload:
    prompt = f"""
    Current Date: {date.today().isoformat()}
    Extract study topics covered and pending assignments or deadlines from this student note:
    "{raw_text}"
    """
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AcademicPayload
        )
    )
    return AcademicPayload.model_validate_json(response.text)

# ----------------- UI Layout -----------------
st.title("🎓 Academic Work & Dues Tracker")

# 1. Quick Ingestion Box
with st.expander("📝 Log Today's Lecture Notes / Deadlines", expanded=True):
    user_input = st.text_area(
        "Dump your raw notes or class updates here:",
        placeholder="e.g., In Math we finished Cayley-Hamilton and Diagonalization. Homework 2 is due Friday. Physics lab record observation due tomorrow."
    )
    if st.button("Analyze & Log", type="primary"):
        if user_input.strip():
            with st.spinner("AI is processing..."):
                extracted = parse_with_ai(user_input)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                
                # Save topics
                for t in extracted.topics:
                    c.execute(
                        "INSERT INTO topics (subject, summary, logged_date) VALUES (?, ?, ?)",
                        (t.subject, t.summary, str(date.today()))
                    )
                # Save dues
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

# 2. Main Dashboard (Two Columns)
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

# 3. Weekly & Daily Summarizer Section
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