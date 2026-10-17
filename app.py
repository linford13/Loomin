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
    ".block-container{padding-top:1rem;max-width:1200px}"
    "[data-testid='stChatInput']{background:#fceee8!important;border-radius:32px!important;padding:6px 14px!important;border:none!important;box-shadow:none!important}"
    "[data-testid='stChatInput']>div{background:transparent!important;border:none!important;box-shadow:none!important}"
    "[data-testid='stChatInput'] textarea{color:#18181b!important;font-size:1rem!important}"
    "[data-testid='stChatInput'] textarea::placeholder{color:#6e655f!important;opacity:1!important}"
    "[data-testid='stChatInput'] button{color:#18181b!important}"
    ".reply-txt{color:#e2e8f0;font-size:0.95rem;margin:6px 0 12px 0}"
    ".sticky{position:relative;background:#fbf7dc;color:#27272a;padding:28px 18px 18px;border-radius:4px;"
    "box-shadow:0 12px 24px rgba(0,0,0,.5);transform:rotate(-1.5deg);min-height:280px;font-family:cursive,sans-serif}"
    ".pin{position:absolute;top:-11px;left:50%;transform:translateX(-50%);width:22px;height:22px;"
    "background:radial-gradient(circle at 35% 35%,#ff4b4b,#8a0b0b);border-radius:50%;box-shadow:0 3px 6px rgba(0,0,0,.5)}"
    ".stitle{font-weight:700;border-bottom:2px dashed #d1c79f;padding-bottom:6px;margin-bottom:10px;text-align:center}"
    ".sitem{font-size:.88rem;margin-bottom:8px;padding-bottom:5px;border-bottom:1px dotted #e2d9b5}"
    "[data-testid='stVerticalBlockBorderWrapper']{border:2.5px solid #ffffff!important;border-radius:28px!important;padding:22px!important;min-height:300px!important;background:#0b0f17!important}"
    "div[data-baseweb='select']>div{background:#1e293b!important;color:#f8fafc!important;border-radius:10px!important;border:1px solid #334155!important;font-weight:600}"
    "</style>",
    unsafe_allow_html=True
)

KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not KEY:
    st.error("Missing GEMINI_API_KEY in Secrets.")
    st.stop()

client = genai.Client(api_key=KEY)
conn = sqlite3.connect("milo_study.db")
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

# Top Layout: Logo on Left, Chat Bar spanning right
top_left, top_right = st.columns([1.2, 3], gap="medium")

with top_left:
    logo_svg = (
        "<svg width='160' height='55' viewBox='0 0 240 80' style='user-select:none;margin-top:5px'>"
        "<text x='5' y='62' fill='#ffffff' font-family='Georgia,serif' font-size='64' letter-spacing='3'>MIL</text>"
        "<line x1='128' y1='61' x2='162' y2='61' stroke='#ffffff' stroke-width='1.5'/>"
        "<text x='158' y='62' fill='#ffffff' font-family='Georgia,serif' font-size='64'>O</text>"
        "<ellipse cx='185' cy='40' rx='38' ry='11' fill='none' stroke='#ffffff' stroke-width='1' transform='rotate(-22 185 40)'/>"
        "<ellipse cx='185' cy='40' rx='38' ry='8' fill='none' stroke='#ffffff' stroke-width='0.8' transform='rotate(-16 185 40)'/>"
        "<text x='144' y='54' fill='#ffffff' font-size='12'>✦</text>"
        "<text x='214' y='34' fill='#ffffff' font-size='12'>✦</text>"
        "</svg>"
    )
    st.markdown(logo_svg, unsafe_allow_html=True)

with top_right:
    prompt = st.chat_input(
        "Ask MILO, paste lecture updates, or drop deadlines...",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "pdf", "txt"]
    )
    if "reply" in st.session_state and st.session_state["reply"]:
        st.markdown("<div class='reply-txt'>" + st.session_state["reply"] + "</div>", unsafe_allow_html=True)

if prompt:
    txt = getattr(prompt, "text", "") or ""
    files = getattr(prompt, "files", []) or []
    if txt.strip() or files:
        items = ["Today is " + date.today().isoformat() + ". Extract topics and dues (YYYY-MM-DD). Set is_study=False if casual chat."]
        if txt.strip():
            items.append(txt)
        for f in files:
            if "image" in f.type:
                items.append(Image.open(f))
            elif "pdf" in f.type:
                items.append("\n".join([p.extract_text() or "" for p in PdfReader(f).pages[:8]])[:5000])
            else:
                items.append(f.read().decode("utf-8")[:5000])
        with st.spinner(""):
            try:
                r = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=items,
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Payload)
                )
                data = r.parsed or Payload.model_validate_json(r.text)
                if not data.is_study:
                    st.session_state["reply"] = data.reply or "Hey! Send class notes or deadlines anytime."
                else:
                    st.session_state["reply"] = ""
                    for t in data.topics:
                        conn.execute("INSERT INTO topics(subject,topic,module,logged_date)VALUES(?,?,?,?)", (t.subject, t.topic, t.module or "General", str(date.today())))
                    for d in data.dues:
                        conn.execute("INSERT INTO dues(subject,task,due_date,status)VALUES(?,?,?,'Pending')", (d.subject, d.task, d.due_date or "TBD"))
                    conn.commit()
                st.rerun()
            except Exception as e:
                st.session_state["reply"] = "Error: " + str(e)
                st.rerun()

st.write("")
st.write("")

# Main Body Grid: Left Sticky Note, Right Discussion Slate
left, right = st.columns([1, 1.8], gap="large")

with left:
    dues = pd.read_sql_query("SELECT * FROM dues WHERE status='Pending' ORDER BY due_date ASC LIMIT 5", conn)
    rows = "".join([
        "<div class='sitem'><b>[" + str(r.subject) + "]</b> " + str(r.task) + "<br><span style='color:#dc2626'>Due: " + str(r.due_date) + "</span></div>"
        for _, r in dues.iterrows()
    ]) or "<div style='text-align:center;padding-top:45px'>No dues pending!</div>"
    st.markdown("<div class='sticky'><div class='pin'></div><div class='stitle'>UPCOMING DUES</div>" + rows + "</div>", unsafe_allow_html=True)
    if not dues.empty:
        with st.expander("Mark Complete"):
            for _, r in dues.iterrows():
                if st.button("✓ " + str(r.subject) + ": " + str(r.task)[:15], key="d" + str(r.id), use_container_width=True):
                    conn.execute("UPDATE dues SET status='Done' WHERE id=?", (int(r.id),))
                    conn.commit()
                    st.rerun()

with right:
    with st.container(border=True):
        sc1, _ = st.columns([1.5, 1.5])
        with sc1:
            mode = st.selectbox("View", ["Today's Discussion", "This Week (Mon - Sun)"], label_visibility="collapsed")
        
        td = date.today()
        mon = td - timedelta(days=td.weekday())
        sun = mon + timedelta(days=6)
        if mode == "Today's Discussion":
            df = pd.read_sql_query("SELECT * FROM topics WHERE logged_date=? ORDER BY id DESC", conn, params=(str(td),))
        else:
            df = pd.read_sql_query("SELECT * FROM topics WHERE logged_date BETWEEN ? AND ? ORDER BY id DESC", conn, params=(str(mon), str(sun)))
        
        items_html = "".join([
            "<div style='margin-top:14px;border-bottom:1px solid #1e293b;padding-bottom:8px'><b>[" + str(r.subject) + "]</b> (" + str(r.module) + "): " + str(r.topic) + " <small style='color:#64748b'>" + str(r.logged_date) + "</small></div>"
            for _, r in df.iterrows()
        ]) or "<p style='color:#64748b;padding-top:45px;text-align:center'>No discussions logged for this period yet.</p>"
        st.markdown(items_html, unsafe_allow_html=True)

conn.close()
