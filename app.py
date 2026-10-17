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

    .milo-logo {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: 2.8rem;
        font-weight: 700;
        letter-spacing: 2px;
        color: #ffffff;
        margin-bottom: 1.5rem;
    }

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
    Convert relative dates ('due Friday', 'tomorrow') to YYYY-MM-DD
