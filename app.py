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
    ".block-container{padding-top:1.8rem;max-width:1150px}"
    "[data-testid='stChatInput']{background:#fceee8!important;border-radius:32px!important;padding:6px 12px!important;border:none!important;box-shadow:none!important}"
    "[data-testid='stChatInput']>div{background:transparent!important;border:none!important;box-shadow:none!important}"
    "[data-testid='stChatInput'] textarea{color:#18181b!important;font-size:1rem!important}"
    "[data-testid='stChatInput'] textarea::placeholder{color:#6e655f!important;opacity:1!important}"
    "[data-testid='stChatInput'] button{color:#18181b!important}"
    ".reply-txt{text-align:center;color:#e2e8f0;font-size:1rem;margin:10px 0 4px 0}"
    ".sticky{position:relative;background:#fbf7dc;color:#27272a;padding:28px 18px 18px;border-radius:4px;"
    "box-shadow:0 12px 24px rgba(0,0,0,.5);transform:rotate(-2deg);min-height:280px;font-family:cursive,sans-serif}"
    ".pin{position:absolute;top:-11px;left:50%;transform:translateX(-50%);width:22px;height:22px;"
    "background:radial-gradient(circle at 35% 35%,#ff4b4b,#8a0b0b);border-radius:50%;box-shadow:0 3px 6px rgba(0,0,0,.5)}"
    ".stitle{font-weight:700;border-bottom:2px dashed #d1c79f;padding-bottom:6px;margin-bottom:10px;text-align:center}"
    ".sitem{font-size:.88rem;margin-bottom:8px;padding-bottom:5px;border-bottom:1px dotted #e2d9b5}"
    "[data-testid='stVerticalBlockBorderWrapper']{border:2.5px solid #ffffff!important;border-radius:28px!important;padding:22px!important;min-height:290px!important;background:#0b0f17!important}"
    "div[data-baseweb='select']>div{background:#e5e7eb!important;color:#111827!important;border-radius:8px!important;border:none!important;font-weight:600}"
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
conn.execute("CREATE TABLE IF NOT EXISTS dues(
