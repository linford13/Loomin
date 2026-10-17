import os, sqlite3
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from pydantic import BaseModel
from typing import List
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

st.set_page_config(page_title="MILO", page_icon="📌", layout="wide")

st.markdown(
    "<style>"
    ".stApp{background:#0b0f17;color:#f1f5f9}"
    ".milo-logo{font:700 2.8rem Georgia,serif;color:#fff;margin-bottom:1.2rem}"
    ".sticky{position:relative;background:#fbf7dc;color:#27272a;padding:26px 18px 18px;border-radius:4px;"
    "box-shadow:0 10px 20px rgba(0,0,0,.45);transform:rotate(-1.5deg);min-height:270px;font-family:cursive,sans-serif}"
    ".pin{position:absolute;top:-11px;left:50%;transform:translateX(-50%);width:22px;height:22px;"
    "background:radial-gradient(circle at 35% 35%,#ff4b4b,#8a0b0b);border-radius:50%;box-shadow:0 3px 6px rgba(0,0,0,.5)}"
    ".stitle{font-weight:700;border-bottom:2px dashed #d1c79f;padding-bottom:6px;margin-bottom:10px;text-align:center}"
    ".sitem{font-size:.88rem;margin-bottom:8px;padding-bottom:5px;border-bottom:1px dotted #e2d9b5}"
    ".stTextInput input{background:#fceee8!important;color:#111!important;border-radius:30px!important;padding:12px 20px!important;border:none!important}"
    "[data-testid='stForm']{border:none!important;padding:0!important}"
    ".dbox{border:2px solid #fff;border-radius:24px;padding:20px;min-height:270px}"
    "</style>",
    unsafe_allow_html=True
)

KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not KEY:
    st.error("Missing GEMINI_API_KEY in Secrets.")
    st.stop()

client = genai.Client(api_key=KEY)
DB = "milo_study.db"

conn = sqlite3.connect(DB)
conn.execute("CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY,subject TEXT,topic TEXT,module TEXT,logged_date TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS dues(id INTEGER PRIMARY KEY,subject TEXT,task TEXT,due_date TEXT,status TEXT)")

class Topic(BaseModel):
    subject: str
    topic: str
    module: str

class Due(BaseModel):
    subject: str
    task: str
    due_date: str

class Payload(BaseModel):
    is_study: bool
    reply: str
    topics: List[Topic]
    dues: List[Due]

st.markdown("<div class='milo-logo'>MILO</div>", unsafe_allow_html=True)

with st.form("chat", clear_on_submit=True):
    c1, c2 = st.columns([10, 2])
    txt = c1.text_input("Msg", placeholder="Ask MILO, paste lecture updates, or drop deadlines...", label_visibility="collapsed")
    send = c2.form_submit_button("Send", use_container_width=True)
    with st.expander("+ Attach Files (Photos, PDFs, Notes)"):
        files = st.file_uploader("Files", type=["png", "jpg", "jpeg", "pdf", "txt"], accept_multiple_files=True, label_visibility="collapsed")

if send and (txt.strip() or files):
    items = ["Today is " + date.today().isoformat() + ". Extract topics and dues (YYYY-MM-DD). Set is_study=False if casual chat."]
    if txt.strip():
        items.append(txt)
    for f in (files or []):
        if "image" in f.type:
            items.append(Image.open(f))
        elif "pdf" in f.type:
            items.append("\n".join([p.extract_text() or "" for p in PdfReader(f).pages[:8]])[:5000])
        else:
            items.append(f.read().decode("utf-8")[:5000])
    with st.spinner("MILO is thinking..."):
        try:
            r = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=items,
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Payload)
            )
            data = r.parsed or Payload.model_validate_json(r.text)
            if not data.is_study:
                st.info(data.reply or "Hey! Send class notes or deadlines to log them.")
            else:
                for t in data.topics:
                    conn.execute("INSERT INTO topics(subject,topic,module,logged_date)VALUES(?,?,?,?)", (t.subject, t.topic, t.module or "General", str(date.today())))
                for d in data.dues:
                    conn.execute("INSERT INTO dues(subject,task,due_date,status)VALUES(?,?,?,'Pending')", (d.subject, d.task, d.due_date or "TBD"))
                conn.commit()
                st.rerun()
        except Exception as e:
            st.error("Error: " + str(e))

left, right = st.columns([1, 2], gap="large")

with left:
    dues = pd.read_sql_query("SELECT * FROM dues WHERE status='Pending' ORDER BY due_date ASC LIMIT 5", conn)
    rows = "".join([
        "<div class='sitem'><b>[" + str(r.subject) + "]</b> " + str(r.task) + "<br><span style='color:#dc2626'>Due: " + str(r.due_date) + "</span></div>"
        for _, r in dues.iterrows()
    ]) or "<div style='text-align:center;padding-top:40px'>No dues pending!</div>"
    st.markdown("<div class='sticky'><div class='pin'></div><div class='stitle'>UPCOMING DUES</div>" + rows + "</div>", unsafe_allow_html=True)
    if not dues.empty:
        with st.expander("Mark Complete"):
            for _, r in dues.iterrows():
                if st.button("Done: " + str(r.subject) + " - " + str(r.task)[:15], key="d" + str(r.id), use_container_width=True):
                    conn.execute("UPDATE dues SET status='Done' WHERE id=?", (int(r.id),))
                    conn.commit()
                    st.rerun()

with right:
    mode = st.selectbox("View", ["Today's Discussion", "This Week (Mon - Sun)"], label_visibility="collapsed")
    td = date.today()
    mon = td - timedelta(days=td.weekday())
    sun = mon + timedelta(days=6)
    if mode == "Today's Discussion":
        df = pd.read_sql_query("SELECT * FROM topics WHERE logged_date=? ORDER BY id DESC", conn, params=(str(td),))
        hdr = "Discussed Today (" + td.strftime("%b %d") + ")"
    else:
        df = pd.read_sql_query("SELECT * FROM topics WHERE logged_date BETWEEN ? AND ? ORDER BY id DESC", conn, params=(str(mon), str(sun)))
        hdr = "Week: " + mon.strftime("%b %d") + " - " + sun.strftime("%b %d")
    items_html = "".join([
        "<div style='margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px'><b>[" + str(r.subject) + "]</b> (" + str(r.module) + "): " + str(r.topic) + " <small style='color:#64748b'>" + str(r.logged_date) + "</small></div>"
        for _, r in df.iterrows()
    ]) or "<p style='color:#64748b;padding-top:30px;text-align:center'>No discussions logged yet.</p>"
    st.markdown("<div class='dbox'><h4 style='margin-top:0;color:#38bdf8'>" + hdr + "</h4>" + items_html + "</div>", unsafe_allow_html=True)

conn.close()
