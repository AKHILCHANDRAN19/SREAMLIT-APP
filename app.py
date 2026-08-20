import streamlit as st
import asyncio
import threading
import re
import gc
import os
import io
import math
import random
import time
import array
import numpy as np
import cv2
import subprocess
import collections
import shutil
from datetime import datetime
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import intro
import thumbnail
import websockets
import requests
import json
import base64
import uuid
import wave

# --- INDIC NUM2WORDS INTEGRATION ---
try:
    from indic_num2words import num2words
except ImportError:
    num2words = None

# ==========================================
# --- USER CONFIGURATION BLOCK ---
# ==========================================

TARGET_CHANNEL_ID = -1003889675767

UPLOAD_COMBINED_ONLY_IN_CUSTOM_RANGE = False

# 1. BASE ANIMATION / SCROLLING DURATIONS (IN SECONDS - EXCLUDING VOICEOVER)
# Note: Scrolling begins strictly AFTER voiceover completes.
# Total duration = Voiceover Audio Duration + BASE_DURATION
DURATION_1ST_PRIZE = 2.5         # Extra holding time after numbers are read
DURATION_2ND_PRIZE = 2.5         # Extra holding time after numbers are read
DURATION_3RD_PRIZE = 2.5         # Extra holding time after numbers are read

DURATION_CONSOLATION = 20.0      # Scroll duration for Consolation
DURATION_4TH_PRIZE = 30.0        # Scroll duration for 4th Prize
DURATION_5TH_PRIZE = 25.0        # Scroll duration for 5th Prize
DURATION_6TH_PRIZE = 35.0        # Scroll duration for 6th Prize
DURATION_7TH_PRIZE = 110.0       # Scroll duration for 7th Prize
DURATION_8TH_PRIZE = 110.0       # Scroll duration for 8th Prize
DURATION_9TH_PRIZE = 110.0       # Scroll duration for 9th Prize

# 2. SCROLL SPEED SETTINGS (END DELAYS IN SECONDS)
CONSOLATION_END_DELAY = 1.0
PRIZE_4TH_END_DELAY = 2.0
PRIZE_5TH_END_DELAY = 2.0
PRIZE_6TH_END_DELAY = 2.0
PRIZE_7_8_9_END_DELAY = 2.0

# 3. VIDEO TRANSITION / FADE SETTINGS (IN SECONDS)
ENABLE_TRANSITIONS = True
TRANSITION_FADE_DURATION = 0.5   # Fade In / Fade Out duration in seconds

# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "renders")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FINAL_OUTPUT_VIDEO = os.path.join(DOWNLOAD_DIR, "final_combined_lottery.mp4")

# Background Audio Paths
BANG_AUDIO_BGM = os.path.join(DOWNLOAD_DIR, "cinematic_bang.wav")

FPS = 30
WIDTH, HEIGHT = 1920, 1080

# ==========================================
# PERSISTENT TELEMETRY & CACHE SINGLETON
# ==========================================
class TelemetryState:
    def __init__(self):
        self.log_history = collections.deque(maxlen=60)
        self.current_status = {"task": "Idle", "progress": 0.0, "details": "Waiting for draw commands..."}
        self.scraped_cache = {}
        self.main_event_loop = None

    def log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self.log_history.append(entry)
        print(entry, flush=True)

    def set_status(self, task: str, progress: float, details: str):
        self.current_status["task"] = task
        self.current_status["progress"] = max(0.0, min(1.0, progress))
        self.current_status["details"] = details

@st.cache_resource
def get_telemetry():
    return TelemetryState()

GLOBAL_STATE = get_telemetry()

# --- FONT LOADER ---
FONTS = {
    "hero": os.path.join(BASE_DIR, "Anton-Regular.ttf"),
    "black": os.path.join(BASE_DIR, "Montserrat-Black.ttf"),
    "extrabold": os.path.join(BASE_DIR, "Montserrat-ExtraBold.ttf"),
    "bold": os.path.join(BASE_DIR, "Montserrat-Bold.ttf")
}

def load_font(font_key, size):
    font_path = FONTS.get(font_key, "")
    if os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def get_audio_duration(audio_path):
    if not os.path.exists(audio_path): return 0.0
    try:
        with wave.open(audio_path, 'rb') as f:
            return f.getnframes() / float(f.getframerate())
    except Exception:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            stdout=subprocess.PIPE, text=True
        )
        try:
            return float(res.stdout.strip())
        except Exception:
            return 0.0

def get_video_duration(video_path):
    if not os.path.exists(video_path): return 0.0
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        stdout=subprocess.PIPE, text=True
    )
    try:
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def format_timestamp(seconds):
    s = int(round(seconds))
    m = s // 60
    sec = s % 60
    return f"{m:02d}:{sec:02d}"

# ==========================================
# PYTHON AUDIO SYNTHESIZERS
# ==========================================
def generate_cinematic_bang(file_path):
    if os.path.exists(file_path): return
    GLOBAL_STATE.log(f"Synthesizing Cinematic Bang Audio to {file_path}...")
    sample_rate = 44100
    duration = 5.0
    total_samples = int(sample_rate * duration)
    
    pcm = array.array('h')
    sub_phase, brass_phase1, brass_phase2 = 0.0, 0.0, 0.0
    l_filter_state, r_filter_state = 0.0, 0.0
    
    for i in range(total_samples):
        t = i / sample_rate
        sub_freq = 28.0 + 102.0 * math.exp(-12.0 * t)
        sub_phase += 2.0 * math.pi * sub_freq / sample_rate
        sub_env = math.exp(-1.4 * t)
        sub_tone = (math.sin(sub_phase) + 0.3 * math.sin(2.0 * sub_phase)) * sub_env
        
        brass_freq = 55.0 * (1.0 - 0.15 * math.exp(-3.0 * t))
        brass_phase1 += 2.0 * math.pi * brass_freq / sample_rate
        brass_phase2 += 2.0 * math.pi * (brass_freq * 1.008) / sample_rate
        brass_tone_l = math.sin(brass_phase1) + 0.5 * math.sin(2.0 * brass_phase1)
        brass_tone_r = math.sin(brass_phase2) + 0.5 * math.sin(2.0 * brass_phase2)
        brass_env = math.exp(-2.2 * t) * (1.0 / (1.0 + math.exp(-100.0 * t)))
        
        raw_noise_l, raw_noise_r = random.uniform(-1.0, 1.0), random.uniform(-1.0, 1.0)
        crack_env = 1.4 * math.exp(-45.0 * t)
        crack_l, crack_r = raw_noise_l * crack_env, raw_noise_r * crack_env
        
        alpha = 0.08 + 0.35 * math.exp(-18.0 * t)
        l_filter_state = alpha * raw_noise_l + (1.0 - alpha) * l_filter_state
        r_filter_state = alpha * raw_noise_r + (1.0 - alpha) * r_filter_state
        tail_env = math.exp(-1.1 * t)
        rumble_l, rumble_r = l_filter_state * tail_env * 0.75, r_filter_state * tail_env * 0.75
        
        mix_l = 0.65 * sub_tone + 0.35 * (brass_tone_l * brass_env) + 0.55 * crack_l + rumble_l
        mix_r = 0.65 * sub_tone + 0.35 * (brass_tone_r * brass_env) + 0.55 * crack_r + rumble_r
        
        out_l = math.tanh(mix_l * 1.5)
        out_r = math.tanh(mix_r * 1.5)
        
        pcm.append(int(max(-32768, min(32767, out_l * 32767 * 0.95))))
        pcm.append(int(max(-32768, min(32767, out_r * 32767 * 0.95))))
        
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

generate_cinematic_bang(BANG_AUDIO_BGM)

# --- HTTP ENGINE ---
try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests as standard_requests
    USE_CURL_CFFI = False

def http_get(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if USE_CURL_CFFI:
        return cffi_requests.get(url, impersonate="chrome", timeout=10)
    return standard_requests.get(url, headers=headers, timeout=10)

# --- COMPLETE MALAYALAM DICTIONARIES ---
ALPHA_TO_ML = {
    'A': 'എ', 'B': 'ബി', 'C': 'സി', 'D': 'ഡി', 'E': 'ഇ', 'F': 'എഫ്',
    'G': 'ജി', 'H': 'എച്ച്', 'I': 'ഐ', 'J': 'ജെ', 'K': 'കെ', 'L': 'എൽ',
    'M': 'എം', 'N': 'എൻ', 'O': 'ഓ', 'P': 'പി', 'Q': 'ക്യു', 'R': 'ആർ',
    'S': 'എസ്', 'T': 'ടി', 'U': 'യു', 'V': 'വി', 'W': 'ഡബ്ല്യു', 'X': 'എക്സ്',
    'Y': 'വൈ', 'Z': 'സെഡ്'
}

DIGITS_TO_ML = {
    '0': 'പൂജ്യം', '1': 'ഒന്ന്', '2': 'രണ്ട്', '3': 'മൂന്ന്', '4': 'നാല്',
    '5': 'അഞ്ച്', '6': 'ആറ്', '7': 'ഏഴ്', '8': 'എട്ട്', '9': 'ഒമ്പത്'
}

ML_PRIZE_WORDS = {
    100000000: "പത്ത് കോടി",
    80000000: "എട്ട് കോടി",
    75000000: "ഏഴര കോടി",
    70000000: "ഏഴ് കോടി",
    10000000: "ഒരു കോടി",
    7500000: "എഴുപത്തിയഞ്ച് ലക്ഷം",
    7000000: "എഴുപത് ലക്ഷം",
    5000000: "അമ്പത് ലക്ഷം",
    3000000: "മുപ്പത് ലക്ഷം",
    2500000: "ഇരുപത്തിയഞ്ച് ലക്ഷം",
    1000000: "പത്ത് ലക്ഷം",
    500000: "അഞ്ച് ലക്ഷം",
    100000: "ഒരു ലക്ഷം",
    50000: "അമ്പതിനായിരം",
    25000: "ഇരുപത്തിയയ്യായിരം",
    10000: "പതിനായിരം",
    8000: "എണ്ണായിരം",
    5000: "അയ്യായിരം",
    2000: "രണ്ടായിരം",
    1000: "ആയിരം",
    500: "അഞ്ഞൂറ്",
    200: "ഇരുന്നൂറ്",
    100: "നൂറ്"
}

ML_DAYS = {
    1: "ഒന്നാം", 2: "രണ്ടാം", 3: "മൂന്നാം", 4: "നാലാം", 5: "അഞ്ചാം",
    6: "ആറാം", 7: "ഏഴാം", 8: "എട്ടാം", 9: "ഒമ്പതാം", 10: "പത്താം",
    11: "പതിനൊന്നാം", 12: "പന്ത്രണ്ടാം", 13: "പതിമൂന്നാം", 14: "പതിനാലാം", 15: "പതിനഞ്ചാം",
    16: "പതിനാറാം", 17: "പതിനേഴാം", 18: "പതിനെട്ടാം", 19: "പത്തൊമ്പതാം", 20: "ഇരുപതാം",
    21: "ഇരുപത്തൊന്നാം", 22: "ഇരുപത്തിരണ്ടാം", 23: "ഇരുപത്തിമൂന്നാം", 24: "ഇരുപത്തിനാലാം", 25: "ഇരുപത്തിയഞ്ചാം",
    26: "ഇരുപത്തിയാറാം", 27: "ഇരുപത്തിയേഴാം", 28: "ഇരുപത്തിയെട്ടാം", 29: "ഇരുപത്തൊമ്പതാം", 30: "മുപ്പതാം",
    31: "മുപ്പത്തൊന്നാം"
}

ML_YEARS = {
    2024: "രണ്ടായിരത്തി ഇരുപത്തിനാല്",
    2025: "രണ്ടായിരത്തി ഇരുപത്തിയഞ്ച്",
    2026: "രണ്ടായിരത്തി ഇരുപത്തിയാറ്",
    2027: "രണ്ടായിരത്തി ഇരുപത്തിയേഴ്",
    2028: "രണ്ടായിരത്തി ഇരുപത്തിയെട്ട്",
    2029: "രണ്ടായിരത്തി ഇരുപത്തൊമ്പത്",
    2030: "രണ്ടായിരത്തി മുപ്പത്"
}

ML_MONTHS = {
    1: "ജനുവരി", 2: "ഫെബ്രുവരി", 3: "മാർച്ച്", 4: "ഏപ്രിൽ",
    5: "മെയ്", 6: "ജൂൺ", 7: "ജൂലൈ", 8: "ആഗസ്റ്റ്",
    9: "സെപ്റ്റംബർ", 10: "ഒക്ടോബർ", 11: "നവംബർ", 12: "ഡിസംബർ"
}

ML_WEEKDAYS = {
    0: "തിങ്കളാഴ്ച", 1: "ചൊവ്വാഴ്ച", 2: "ബുധനാഴ്ച", 3: "വ്യാഴാഴ്ച",
    4: "വെള്ളിയാഴ്ച", 5: "ശനിയാഴ്ച", 6: "ഞായറാഴ്ച"
}

def to_tts_format(ticket_str: str) -> str:
    ticket_clean = re.sub(r'\(.*?\)|\[.*?\]', '', ticket_str).strip()
    match_series = re.match(r'^([A-Za-z]{2})\s*(\d{6})', ticket_clean)
    if match_series:
        series, number = match_series.group(1).upper(), match_series.group(2)
        s_parts = [ALPHA_TO_ML.get(c, c) for c in series]
        n_parts = [DIGITS_TO_ML.get(d, d) for d in number]
        return " , ".join(s_parts + n_parts)
    else:
        only_digits = re.findall(r'\d', ticket_clean)
        if only_digits:
            n_parts = [DIGITS_TO_ML.get(d, d) for d in only_digits]
            return " , ".join(n_parts)
        return ticket_clean

def get_malayalam_prize_money(amount_str):
    clean_str = re.sub(r'\[.*?\]|\(.*?\)', '', str(amount_str))
    clean_num = re.sub(r'[^\d]', '', clean_str)
    if not clean_num: return ""
    try:
        val = int(clean_num)
        if val in ML_PRIZE_WORDS:
            return ML_PRIZE_WORDS[val]
        if num2words:
            try:
                converted = num2words(val, lang='ml')
                if converted and converted.strip():
                    return converted.strip()
            except Exception:
                pass
        return str(val)
    except Exception:
        return clean_num

# ==========================================
# CARTESIA TTS ENGINE
# ==========================================
CARTESIA_VIJAY_ID = "374b80da-e622-4dfc-90f6-1eeb13d331c9"

def get_public_token_sync():
    url = "https://backend.cartesia.ai/access-token/public"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Referer": "https://cartesia.ai/languages/malayalam"
    }
    try:
        if USE_CURL_CFFI:
            response = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=8)
        else:
            response = requests.get(url, headers=headers, timeout=8)
        if response.status_code == 200:
            data = response.json()
            tok = data.get("token", data.get("access_token"))
            if tok: return tok
    except Exception as e:
        GLOBAL_STATE.log(f"Token acquisition notice: {e}")
    return None

async def get_public_token():
    return await asyncio.to_thread(get_public_token_sync)

async def generate_cartesia_audio(text, output_filename, token=None, retries=3):
    if not text or not text.strip(): return False
    
    for attempt in range(retries):
        current_token = token or await get_public_token()
        if not current_token:
            await asyncio.sleep(1)
            continue
            
        ws_url = f"wss://api.cartesia.ai/tts/websocket?cartesia_version=2024-06-10&api_key={current_token}"
        payload = {
            "context_id": str(uuid.uuid4()),
            "model_id": "sonic-3",
            "transcript": text,
            "language": "ml",
            "voice": {"mode": "id", "id": CARTESIA_VIJAY_ID},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 44100}
        }
        try:
            async with websockets.connect(ws_url, ping_interval=None) as ws:
                await ws.send(json.dumps(payload))
                audio_buffer = bytearray()
                while True:
                    response_str = await asyncio.wait_for(ws.recv(), timeout=12.0)
                    response = json.loads(response_str)
                    if response.get("type") == "chunk":
                        audio_buffer.extend(base64.b64decode(response["data"]))
                    elif response.get("type") == "done":
                        with wave.open(output_filename, "wb") as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2)
                            wav_file.setframerate(44100)
                            wav_file.writeframes(audio_buffer)
                        return True
                    elif response.get("type") == "error":
                        GLOBAL_STATE.log(f"Cartesia Error: {response.get('error')}")
                        break
        except Exception as e:
            GLOBAL_STATE.log(f"Cartesia WebSocket (Attempt {attempt+1}/{retries}): {e}")
            token = None
            await asyncio.sleep(1.5)
    return False

def concat_wav_files(file1, file2, out_file):
    try:
        with wave.open(file1, 'rb') as w1, wave.open(file2, 'rb') as w2:
            data = w1.readframes(w1.getnframes()) + w2.readframes(w2.getnframes())
            params = w1.getparams()
        with wave.open(out_file, 'wb') as out_w:
            out_w.setparams(params)
            out_w.writeframes(data)
        return True
    except Exception as e:
        GLOBAL_STATE.log(f"Audio Concat Notice: {e}")
        return False

# ==========================================
# 1. SCRAPING LOGIC (BLOGGER JSON API PARSER)
# ==========================================
YEAR_BLACKLIST = {"2024", "2025", "2026", "2027", "2028", "2029", "2030"}

def fetch_last_10_draws():
    """Fetches real-time last 10 draws from Blogger JSON API, bypassing static landing posts."""
    cache_buster = int(time.time())
    url = f"https://www.keralalotteries.net/feeds/posts/default?alt=json&max-results=10&_nocache={cache_buster}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    draws = []
    try:
        if USE_CURL_CFFI:
            res = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=10)
        else:
            res = standard_requests.get(url, headers=headers, timeout=10)
            
        data = res.json()
        entries = data.get("feed", {}).get("entry", [])

        for entry in entries:
            raw_title = entry.get("title", {}).get("$t", "")
            
            # Find the canonical web URL
            post_url = ""
            for link in entry.get("link", []):
                if link.get("rel") == "alternate":
                    post_url = link.get("href", "")
                    break

            # 1. Skip generic static landing post
            if "today-kerala-lottery-result-live" in post_url:
                continue

            # 2. Extract Date (DD-MM-YYYY)
            date_match = re.search(r'(\d{2})[./-](\d{2})[./-](\d{4})', raw_title) or \
                         re.search(r'(\d{2})[./-](\d{2})[./-](\d{4})', post_url)
            if not date_match:
                continue

            d_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

            # 3. Clean Title
            clean_title = re.sub(r'(?i)\b(?:Kerala Lotteries Results?:?|Kerala Lottery Results?:?|Lottery Result|Official Result|Results? Today|Live)\b', '', raw_title)
            clean_title = re.sub(r'\d{2}[./-]\d{2}[./-]\d{4}', '', clean_title)
            clean_title = re.sub(r'[:—\-~]', ' ', clean_title)
            clean_title = re.sub(r'\s+', ' ', clean_title).strip().upper()

            if not any(d['date'] == d_str for d in draws):
                draws.append({'date': d_str, 'title': clean_title or d_str, 'url': post_url})

            if len(draws) >= 10:
                break

        return draws
    except Exception as e:
        GLOBAL_STATE.log(f"Error fetching JSON feed draws: {e}")
        return []

def clean_prize_heading(raw_str):
    s = raw_str.replace('\xa0', ' ').strip().upper()
    s = re.sub(r'(?i)RS\.?\s*:?\s*', '₹', s)
    s = s.replace('/-', '').replace('—', ' - ').replace('-', ' - ')
    if '₹' in s:
        parts = s.split('₹', 1)
        prize_part = parts[0].replace(':', '').replace('-', '').strip()
        money_part = parts[1].strip()
        s = f"{prize_part} — ₹{money_part}"
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def parse_lottery_result_page(target_url: str):
    try:
        res = http_get(target_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        post_body = soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse body.", None, {}, None, {}, {}, None

        h1_tag = soup.find('h1', class_='entry-title')
        raw_title = h1_tag.get_text(strip=True) if h1_tag else "KERALA LOTTERY"
        blacklist_regex = r'(?i)\b(?:KERALA|LOTTERIES|LOTTERY|RESULTS?|TODAY|OFFICIAL|LIVE)\b|\d{2}[/.-]\d{2}[/.-]\d{4}|:'
        clean_lottery_title = re.sub(blacklist_regex, '', raw_title)
        clean_lottery_title = re.sub(r'\s+', ' ', clean_lottery_title).strip().upper()

        full_raw_text = post_body.get_text(separator=' ').replace('\xa0', ' ')

        # Extract Date
        date_match = re.search(r'(\d{2})\s*[./-]\s*(\d{2})\s*[./-]\s*(\d{4})', target_url) or \
                     re.search(r'(\d{2})\s*[./-]\s*(\d{2})\s*[./-]\s*(\d{4})', raw_title) or \
                     re.search(r'(\d{2})\s*[./-]\s*(\d{2})\s*[./-]\s*(\d{4})', full_raw_text)
        draw_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else "N/A"

        # Malayalam Name Extraction (Ignores "Live Draw Started" box)
        malayalam_name_series = clean_lottery_title
        ml_patterns = [
            r'ഇന്നത്തെ\s*കേരളാ\s*ലോട്ടറി\s*റിസൾട്ട്\s*([^\n<]+)',
            r'ധനലക്ഷ്മി\s*[^\n<]+',
            r'സ്ത്രീ\s*ശക്തി\s*[^\n<]+',
            r'ഭാഗ്യതാര\s*[^\n<]+',
            r'കാരുണ്യ\s*പ്ലസ്\s*[^\n<]+',
            r'സുവർണ\s*കേരളം\s*[^\n<]+',
            r'കാരുണ്യ\s*[^\n<]+',
            r'സമൃദ്ധി\s*[^\n<]+'
        ]
        for pat in ml_patterns:
            ml_m = re.search(pat, full_raw_text)
            if ml_m:
                cand = ml_m.group(0 if '(' not in pat else 1).strip()
                cand = re.sub(r'(?i)\b(?:Live|@\s*\d+:\d+[a-z]*|Winners|Numbers|Date of Draw|ഫലം)\b', '', cand)
                cand = re.sub(r'[:—\-~]', ' ', cand)
                cand = re.sub(r'\s+', ' ', cand).strip()
                if len(cand) >= 3 and "ആരംഭിച്ചു" not in cand and "തുടരുക" not in cand:
                    malayalam_name_series = cand
                    break

        series_match = re.search(r'Today Lottery Series:\s*([A-Z0-9,\s]+)', full_raw_text)
        series_str = series_match.group(1).strip() if series_match else "N/A"

        # Prepare line-by-line parsing
        for tag in post_body.find_all(['br', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'li', 'table']):
            tag.insert_after('\n')
        lines = [re.sub(r'\s+', ' ', line).strip() for line in post_body.get_text().split('\n') if line.strip()]

        prize_headers = ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]
        prizes_data = {k: [] for k in prize_headers}
        prize_headings = {}
        prize_money_ml = {}
        current_prize_key = None

        for line in lines:
            # Stop before repeated numbers / disclaimers
            if any(sp in line.lower() for sp in ["prize winners are advised to verify", "government gazette", "tomorrow draw details", "repeated draw numbers"]):
                break
            
            matched_header = next((ph for ph in prize_headers if ph.lower() in line.lower()), None)
            if matched_header:
                current_prize_key = matched_header
                if current_prize_key not in prize_headings:
                    cln_head = clean_prize_heading(line)
                    prize_headings[current_prize_key] = cln_head
                    if '₹' in cln_head:
                        money_str = cln_head.split('₹')[-1].strip()
                        prize_money_ml[current_prize_key] = get_malayalam_prize_money(money_str)
                    else:
                        prize_money_ml[current_prize_key] = ""
                continue

            if current_prize_key:
                if (line.startswith("(") and line.endswith(")")) or line in ["...", "---", "***"]:
                    continue
                if "Results Loading" in line:
                    continue

                if current_prize_key in ["1st Prize", "2nd Prize", "3rd Prize"]:
                    ticket_match = re.search(r'([A-Za-z]{2}\s*\d{6}(?:\s*\([A-Za-z\s]+\))?)', line)
                    if ticket_match:
                        prizes_data[current_prize_key].append(ticket_match.group(1).strip())
                elif current_prize_key == "Consolation Prize":
                    cons_tickets = re.findall(r'\b[A-Za-z]{2}\s*\d{6}\b', line)
                    if cons_tickets:
                        prizes_data[current_prize_key].extend(cons_tickets)
                else:
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    # Filter out year numbers (2024-2030) so years never become winning numbers
                    filtered = [d for d in four_digits if d not in YEAR_BLACKLIST]
                    if filtered:
                        prizes_data[current_prize_key].extend(filtered)

        prizes_data = {k: v for k, v in prizes_data.items() if v}

        # Build output message
        msg_output = [f"🎟️ **{clean_lottery_title}**", f"📅 **Date:** `{draw_date}`", f"🔢 **Series:** `{series_str}`", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        prize_order = [("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"), ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣"), ("7th Prize", "7️⃣"), ("8th Prize", "8️⃣"), ("9th Prize", "9️⃣")]

        for p_key, emoji in prize_order:
            if p_key in prizes_data and prizes_data[p_key]:
                formatted_val = "  ".join(prizes_data[p_key]) if "Prize" in p_key and "1st" not in p_key and "2nd" not in p_key and "3rd" not in p_key and "Consolation" not in p_key else "\n".join(prizes_data[p_key])
                msg_output.append(f"{emoji} **{prize_headings.get(p_key, p_key)}**\n`{formatted_val}`\n")

        # Build 100% Malayalam TTS Output
        tts_output = {}
        try:
            d = datetime.strptime(draw_date, "%d-%m-%Y")
            y_sp = ML_YEARS.get(d.year, get_malayalam_prize_money(str(d.year)))
            m_sp = ML_MONTHS.get(d.month, "")
            d_sp = ML_DAYS.get(d.day, f"{get_malayalam_prize_money(str(d.day))} ആം")
            w_sp = ML_WEEKDAYS.get(d.weekday(), "")
            dynamic_intro = f"ഇന്ന് {y_sp} {m_sp} മാസം {d_sp} തീയതി {w_sp} നടന്ന {malayalam_name_series} ലോട്ടറിയുടെ ഔദ്യോഗിക ഫലങ്ങളാണ് ഇപ്പോൾ പ്രഖ്യാപിക്കുന്നത്."
        except Exception:
            dynamic_intro = f"ഇന്ന് നടന്ന {malayalam_name_series} ലോട്ടറിയുടെ ഔദ്യോഗിക ഫലങ്ങളാണ് ഇപ്പോൾ പ്രഖ്യാപിക്കുന്നത്."

        tts_output["Intro"] = dynamic_intro

        prize_ml_names = {
            "1st Prize": "ഒന്നാം", "Consolation Prize": "സമാശ്വാസ", "2nd Prize": "രണ്ടാം",
            "3rd Prize": "മൂന്നാം", "4th Prize": "നാലാം", "5th Prize": "അഞ്ചാം",
            "6th Prize": "ആറാം", "7th Prize": "ഏഴാം", "8th Prize": "എട്ടാം", "9th Prize": "ഒമ്പതാം"
        }
        two_step_prizes = ["1st Prize", "2nd Prize", "3rd Prize", "5th Prize"]
        tts_file_blocks = [f"[Intro Header]\n{dynamic_intro}"]

        for p_key in prize_headers:
            if p_key in prizes_data and prizes_data[p_key]:
                money_txt = prize_money_ml.get(p_key, "")
                p_name_ml = prize_ml_names.get(p_key, "")
                
                if "Consolation" in p_key:
                    header_sentence = f"{money_txt} രൂപയുടെ {p_name_ml} സമ്മാനം ലഭിച്ച അക്കങ്ങൾ"
                elif p_key == "1st Prize":
                    header_sentence = f"{dynamic_intro} {money_txt} രൂപയുടെ {p_name_ml} സമ്മാനത്തിന് അർഹമായ അക്കങ്ങൾ താഴെ പറയുന്നവയാണ്"
                elif p_key in ["2nd Prize", "3rd Prize"]:
                    header_sentence = f"{money_txt} രൂപയുടെ {p_name_ml} സമ്മാനത്തിന് അർഹമായ അക്കങ്ങൾ താഴെ പറയുന്നവയാണ്"
                else:
                    header_sentence = f"{money_txt} രൂപയുടെ {p_name_ml} സമ്മാനത്തിന് അർഹമായ അവസാന നാല് അക്കങ്ങൾ"

                if p_key in two_step_prizes:
                    num_spoken_list = [to_tts_format(x) for x in prizes_data[p_key]]
                    numbers_sentence = " , ".join(num_spoken_list)
                    tts_output[p_key] = {"header": header_sentence, "numbers": numbers_sentence}
                    tts_file_blocks.append(f"[{p_key} Header]\n{header_sentence}\n\n[{p_key} Numbers]\n{numbers_sentence}")
                else:
                    tts_output[p_key] = {"header": header_sentence, "numbers": ""}
                    tts_file_blocks.append(f"[{p_key} Header]\n{header_sentence}")

        tts_string = "\n\n".join(tts_file_blocks)

        # Cache ONLY when 9th prize is completed (never cache partial live data)
        is_fully_complete = "9th Prize" in prizes_data and len(prizes_data["9th Prize"]) >= 100
        if is_fully_complete:
            GLOBAL_STATE.scraped_cache[draw_date] = {
                "text_msg": "\n".join(msg_output),
                "tts_txt": tts_string,
                "tts_dict": tts_output,
                "draw_date": draw_date,
                "prizes": prizes_data,
                "prize_headings": prize_headings,
                "lottery_title": clean_lottery_title,
                "target_url": target_url
            }

        return "\n".join(msg_output), tts_string, tts_output, draw_date, prizes_data, prize_headings, clean_lottery_title
    except Exception as e:
        GLOBAL_STATE.log(f"Parsing Error: {e}")
        return None, None, {}, None, {}, {}, None

# ==========================================
# 2. YOUTUBE METADATA & DYNAMIC TIMESTAMPS GENERATOR
# ==========================================
def generate_youtube_package(lottery_title, draw_date, video_durations_map, prizes_data=None):
    code_match = re.search(r'([A-Za-z]{1,3}[-\s]*\d{1,4})', lottery_title)
    if code_match:
        code_str = code_match.group(1).replace(" ", "-").upper()
        name_str = lottery_title.replace(code_match.group(0), "").strip()
    else:
        code_str = "DL-65"
        name_str = lottery_title.strip()

    name_clean = re.sub(r'[^A-Z0-9]', '', name_str.upper())
    code_clean = re.sub(r'[^A-Z0-9]', '_', code_str.upper())

    try:
        d = datetime.strptime(draw_date, "%d-%m-%Y")
        date_dot = d.strftime("%d.%m.%Y")
        date_slash = d.strftime("%d/%m/%Y")
        date_dash = d.strftime("%d-%m-%Y")
        date_short = f"{d.day}.{d.month}.{str(d.year)[2:]}"
        date_und = d.strftime("%d_%m_%Y")
    except Exception:
        date_dot = draw_date.replace("-", ".")
        date_slash = draw_date.replace("-", "/")
        date_dash = draw_date
        date_short = draw_date
        date_und = draw_date.replace("-", "_")

    prizes = prizes_data or {}

    def get_clean_num(p_key):
        items = prizes.get(p_key, [])
        if items:
            t = items[0]
            dist_match = re.search(r'\(.*?\)', t)
            if dist_match:
                t = t.replace(dist_match.group(0), "").strip()
            return t
        return ""

    num_1st = get_clean_num("1st Prize")
    num_2nd = get_clean_num("2nd Prize")
    num_3rd = get_clean_num("3rd Prize")

    all_tier_keys = [
        "Intro", "1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize",
        "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"
    ]

    tier_labels = {
        "Intro": "Intro & Live Broadcast",
        "1st Prize": f"{lottery_title} 1st Prize: {num_1st}" if num_1st else f"{lottery_title} 1st Prize",
        "Consolation Prize": "Consolation Prize",
        "2nd Prize": f"2nd Prize: {num_2nd}" if num_2nd else "2nd Prize",
        "3rd Prize": f"3rd Prize: {num_3rd}" if num_3rd else "3rd Prize",
        "4th Prize": "4th Prize",
        "5th Prize": "5th Prize",
        "6th Prize": "6th Prize",
        "7th Prize": "7th Prize",
        "8th Prize": "8th Prize",
        "9th Prize": "9th Prize"
    }

    timestamps_lines = []
    current_time = 0.0
    last_rendered_index = -1

    for idx, key in enumerate(all_tier_keys):
        if key in video_durations_map:
            ts_str = format_timestamp(current_time)
            lbl = tier_labels.get(key, key)
            timestamps_lines.append(f"{ts_str} - {lbl}")
            dur = video_durations_map[key]
            current_time += dur
            last_rendered_index = idx

    # Conditional Trailing Timestamps for remaining unrendered prize numbers
    if last_rendered_index != -1 and last_rendered_index < (len(all_tier_keys) - 1):
        ts_future = format_timestamp(current_time)
        last_key = all_tier_keys[last_rendered_index]
        
        if last_key in ["Intro", "1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", "4th Prize", "5th Prize", "6th Prize"]:
            timestamps_lines.append(f"{ts_future} - 7th, 8th & 9th Prize Numbers")
        elif last_key == "7th Prize":
            timestamps_lines.append(f"{ts_future} - 8th & 9th Prize Numbers")
        elif last_key == "8th Prize":
            timestamps_lines.append(f"{ts_future} - 9th Prize Numbers")

    timestamps_text = "\n".join(timestamps_lines)

    title_1 = f"KERALA LOTTERY {name_str} {code_str}| LIVE LOTTERY RESULT TODAY {date_dot}| KERALA LOTTERY LIVE RESULT|"
    title_2 = f"KERALA {name_str} {code_str} KERALA LOTTERY RESULT {date_short} | LIVE KERALA LOTTERY RESULT TODAY."

    description = f"""{title_1}
#{name_clean} #{code_clean} #{date_und} #KeralaLotteryLiveResult #KeralaLottery

⏱️ TIMESTAMPS:
{timestamps_text}

📲 Join our FREE WhatsApp Channel for Instant PDF Updates & Weekly Analysis (Link in About Section / Description)!

Query Solved.
kerala lottery result
Kerala lottery result live
kerala lottery result live today
Kerala Lottery Result Today
kerala lottery results
Kerala lottery today result
live kerala lottery today result
lottery result
Lottery results
lottery results today
today lottery
today lottery result

#KeralaLotteryLiveResult
#{name_clean}
#{name_clean}_{date_slash}
#{name_clean.lower()}_{code_str.lower()}_{date_dash}
#keralalotteryresult
#lotteryresult
#lotteryliveresult
#{name_clean}_result
#{name_clean}_liveresult

{name_str.lower()} kerala lottery live result
{name_str} kerala lottery result
kerala lottery live result {name_str.lower()}
kerala lottery result {name_str}

{name_str} live today
{name_str} {date_slash} live today

Kerala Lottery Result Today {name_str}
Kerala Lottery Result Today {name_str} {code_str}
Kerala Lottery Result Today {name_str} {date_slash}

kerala lottery results {name_str}
kerala lottery results {name_str} {code_str}
kerala lottery results {name_str} {date_slash}

{name_str} live today
{name_str} {code_str} live today
{name_str} {date_slash} live today

Keralalotteries.com {name_str}
Keralalotteries.com {name_str} {code_str}
Keralalotteries.com {name_str} {date_slash}

live kerala lottery result {name_str}
live kerala lottery result {name_str} {code_str}
live kerala lottery result {name_str} {date_slash}

{name_str} kerala lottery
{name_str} {date_slash} kerala lottery
{name_str} kerala lottery result
{name_str} {code_str} kerala lottery result
{name_str} {date_slash} kerala lottery result

{name_str} lottery result
{name_str} {date_slash} lottery result

today kerala lottery
today kerala result
today result kerala
result today kerala lottery
today lottery
lottery today
kerala lottery today

_{name_clean}_{date_slash}
_{date_slash}_{name_clean}

{code_str.lower()}_{name_clean.lower()}_{date_dash}
{code_str.lower()}_{date_dash}_{name_clean.lower()}

{name_clean}_{date_slash}
{name_clean}_{date_dot}_
{date_slash}_{name_clean}_
{date_dot}_{name_clean}

{name_str} today live result
{name_str} kerala today live result
{name_str} live result kerala
{name_str} kerala lottery

today live result
kerala today live result
live result kerala
kerala lottery

{date_slash} today live result
{date_slash} kerala today live result
{date_slash} live result kerala
{date_slash} kerala lottery

{date_dot} Kerala Lottery Result
kerala lottery result
Kerala Lottery Result {date_dot}
Kerala Lottery Result {date_short}
Kerala lottery result live
kerala lottery result live today
Kerala Lottery Result Today

Kerala Lottery Result {code_str}
Kerala Lottery Result {code_clean}
kerala lottery result {name_str}
Kerala Lottery Result {name_str.lower()} {code_str}
Kerala Lottery Result {name_str.lower()} {code_clean}
kerala lottery result {name_str}
Kerala Lottery Result {name_str} {code_str}
Kerala Lottery Result {name_str} {code_clean}

{code_str}
{code_str} Kerala Lottery Result
{code_str} {name_str.lower()}
{code_str} {name_str}
{code_clean}
{code_clean} Kerala Lottery Result
{code_clean} {name_str.lower()}
{code_clean} {name_str}
{name_str.lower()}
{name_str.lower()} kerala lottery result
{name_str.lower()} {code_str}
{name_str.lower()} {code_str} Kerala Lottery Result
{name_str.lower()} {code_clean}
{name_str.lower()} {code_clean} Kerala Lottery Result
{name_str}
{name_str} kerala lottery result
{name_str} {code_str}
{name_str} {code_str} Kerala Lottery Result
{name_str} {code_clean}
{name_str} {code_clean} Kerala Lottery Result

Disclaimer:-
Copyright Disclaimer Under Section 107 of the Copyright Act 1976 allowance is made for "fair use" for purposes such as criticism comment news reporting teaching scholarship and research. Fair use is a use permitted by copyright statute that might otherwise be infringing. Non-profit educational or personal use tips the balance in favor of fair use.

There Was Not Sell Lottery Tickets and Any illegal Products There Was Play Only New Updates about Government Lotteries And Winners Details of Paper Lottery.

Information given in the video is only for Educational Purposes. Viewers should do their own research before playing or investing anything. Also please check lottery rules in your country and state before purchasing as we are not promoting anything.

The prize winners are advised to verify the winning numbers with the results published in the Kerala Government Gazette."""

    tags = f"kerala lottery result live, live kerala lottery result, kerala lottery result, kerala lottery result today, kerala lottery today result, kerala lottery, lottery result today, today lottery result, today's lottery results, {name_str}, {name_str} lottery result, {name_str} result, {name_str} lottery {code_str}, {date_short} lottery result"

    return title_1, title_2, description, tags

async def broadcast_to_channel(client, text=None, video_path=None, audio_path=None, document=None, photo_path=None, caption=""):
    if not TARGET_CHANNEL_ID: return
    try:
        if text:
            chunks = [text[i:i+3500] for i in range(0, len(text), 3500)]
            for chunk in chunks:
                await client.send_message(TARGET_CHANNEL_ID, chunk)
                await asyncio.sleep(0.4)
        elif photo_path and os.path.exists(photo_path):
            await client.send_photo(TARGET_CHANNEL_ID, photo=photo_path, caption=caption)
        elif video_path and os.path.exists(video_path):
            await client.send_video(TARGET_CHANNEL_ID, video=video_path, caption=caption)
        elif audio_path and os.path.exists(audio_path):
            await client.send_audio(TARGET_CHANNEL_ID, audio=audio_path, caption=caption)
        elif document:
            await client.send_document(TARGET_CHANNEL_ID, document=document, caption=caption)
    except Exception as e:
        GLOBAL_STATE.log(f"Channel Broadcast Error: {e}")

async def send_yt_metadata_package(client, chat_id, title_1, title_2, yt_desc, yt_tags):
    # 1. Send Titles (Copyable)
    t_msg = f"🏷️ **YOUTUBE TITLE (OPTION 1):**\n`{title_1}`\n\n🏷️ **YOUTUBE TITLE (OPTION 2):**\n`{title_2}`"
    await client.send_message(chat_id, t_msg)
    if chat_id != TARGET_CHANNEL_ID:
        await broadcast_to_channel(client, text=t_msg)
    await asyncio.sleep(0.4)

    # 2. Send Description & Timestamps in auto-chunks to prevent MessageTooLong
    desc_chunks = [yt_desc[i:i+3500] for i in range(0, len(yt_desc), 3500)]
    for idx, chunk in enumerate(desc_chunks):
        header = f"📝 **YOUTUBE DESCRIPTION & TIMESTAMPS (PART {idx+1}/{len(desc_chunks)} - TAP TO COPY):**\n" if len(desc_chunks) > 1 else "📝 **YOUTUBE DESCRIPTION & TIMESTAMPS (TAP TO COPY):**\n"
        d_msg = f"{header}```{chunk}```"
        await client.send_message(chat_id, d_msg)
        if chat_id != TARGET_CHANNEL_ID:
            await broadcast_to_channel(client, text=d_msg)
        await asyncio.sleep(0.4)

    # 3. Send Tags (Copyable)
    tag_chunks = [yt_tags[i:i+3500] for i in range(0, len(yt_tags), 3500)]
    for chunk in tag_chunks:
        g_msg = f"🏷️ **YOUTUBE TAGS (TAP TO COPY):**\n`{chunk}`"
        await client.send_message(chat_id, g_msg)
        if chat_id != TARGET_CHANNEL_ID:
            await broadcast_to_channel(client, text=g_msg)
        await asyncio.sleep(0.4)

# ==========================================
# 3. UTILITIES & BACKGROUND PRE-RENDERER
# ==========================================
def ease_out_expo(x): return 1 if x == 1 else 1 - math.pow(2, -10 * x)
def ease_in_out_cubic(x): return 4 * x**3 if x < 0.5 else 1 - math.pow(-2 * x + 2, 3) / 2
def ease_out_back_extreme(x): return 1 + 3.5 * math.pow(x - 1, 3) + 2.5 * math.pow(x - 1, 2)

def generate_vertical_gradient(w, h, stops):
    gradient = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / float(h - 1 if h > 1 else 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i+1][0]:
                range_t = (t - stops[i][0]) / (stops[i+1][0] - stops[i][0])
                c1, c2 = np.array(stops[i][1]), np.array(stops[i+1][1])
                c = c1 + (c2 - c1) * range_t
                gradient[y, :] = [int(c[0]), int(c[1]), int(c[2]), 255]
                break
    return Image.fromarray(gradient, mode="RGBA")

def pre_render_background(theme="blue"):
    themes = {
        "purple": (35, 5, 25, 30, 10, 35),
        "blue": (10, 25, 50, 5, 10, 30),
        "silver": (45, 45, 50, 20, 20, 25),
        "gold": (50, 35, 10, 30, 20, 5)
    }
    if theme not in themes: theme = "blue"
    r1, g1, b1, r2, g2, b2 = themes[theme]
    
    y_coords, x_coords = np.ogrid[:HEIGHT, :WIDTH]
    cx, cy = WIDTH / 2, HEIGHT / 2
    norm_dist = np.clip(np.hypot(x_coords - cx, y_coords - cy) / math.hypot(cx, cy), 0, 1)
    
    r = (r1 + (r2 - r1) * (norm_dist ** 1.8)).astype(np.uint8)
    g = (g1 + (g2 - g1) * (norm_dist ** 1.8)).astype(np.uint8)
    b = (b1 + (b2 - b1) * (norm_dist ** 1.8)).astype(np.uint8)
    a = np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)
    
    canvas = Image.fromarray(np.dstack((r, g, b, a)), mode="RGBA")
    
    bl = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_color = (255, 80, 120, 80) if theme == "purple" else (80, 150, 255, 80) if theme == "blue" else (255, 215, 0, 60)
    ImageDraw.Draw(bl).ellipse([int(cx - 700), int(cy - 200), int(cx + 700), int(cy + 450)], fill=glow_color)
    canvas.alpha_composite(bl.filter(ImageFilter.GaussianBlur(150)))
    return canvas

def pre_render_glass_card(district_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    f_sub = load_font("bold", 48) 
    f_main = load_font("black", 85) 
    
    bbox = draw.textbbox((0, 0), district_text, font=f_main)
    text_w = bbox[2] - bbox[0]
    box_w = max(920, text_w + 160)
    x1 = (WIDTH // 2) - (box_w // 2)
    x2 = (WIDTH // 2) + (box_w // 2)
    bounds = [x1, 780, x2, 1000]
    
    draw.rounded_rectangle(bounds, radius=30, fill=(20, 10, 35, 230), outline=(255, 215, 0, 190), width=4)
    draw.rounded_rectangle([bounds[0]+2, bounds[1]+2, bounds[2]-2, bounds[3]-2], radius=28, outline=(255, 255, 255, 100), width=2)
    
    draw.text((WIDTH//2, 835), "WINNING DISTRICT", font=f_sub, fill="#B8C0D0", anchor="mm")
    main_y = 925
    
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    ImageDraw.Draw(glow).text((WIDTH//2, main_y), district_text, font=f_main, fill=(255, 215, 0, 120), anchor="mm")
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(15)))
    
    draw.text((WIDTH//2, main_y + 5), district_text, font=f_main, fill=(0,0,0,230), anchor="mm")
    draw.text((WIDTH//2, main_y), district_text, font=f_main, fill="#FFFFFF", anchor="mm")
    return layer

def pre_render_ribbon_bang(title_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH//2, 310
    font = load_font("extrabold", 44)
    
    bbox = draw.textbbox((0, 0), title_text.upper(), font=font)
    text_w = bbox[2] - bbox[0]
    w = max(1040, text_w + 120)
    h = 130
    x1, y1 = cx - w//2, cy - h//2
    x2, y2 = cx + w//2, cy + h//2
    
    mask_c = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask_c).rectangle([x1, y1, x2, y2], fill=255)
    
    stops = [(0.0, (255, 245, 180)), (0.15, (255, 215, 0)), (0.85, (230, 150, 0)), (1.0, (180, 100, 0))]
    grad = generate_vertical_gradient(WIDTH, h, stops)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    grad_layer.paste(grad, (0, y1))
    layer.paste(grad_layer, (0,0), mask_c)
    draw.rectangle([x1, y1, x2, y2], outline=(255, 235, 120, 255), width=3)
    
    draw.text((cx, cy-2), title_text.upper(), font=font, fill=(255, 224, 102, 255), anchor="mm") 
    draw.text((cx, cy-5), title_text.upper(), font=font, fill=(58, 5, 0, 255), anchor="mm")
    
    shadow = layer.copy().filter(ImageFilter.GaussianBlur(15))
    shadow_data = np.array(shadow)
    shadow_data[..., :3] = 0
    final = Image.fromarray(shadow_data)
    final.alpha_composite(layer)
    return final

def pre_render_ribbon_scroll(title_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH//2, 280
    font = load_font("extrabold", 44)
    
    bbox = draw.textbbox((0, 0), title_text.upper(), font=font)
    text_w = bbox[2] - bbox[0]
    w = max(1040, text_w + 120)
    h = 120
    x1, y1 = cx - w//2, cy - h//2
    x2, y2 = cx + w//2, cy + h//2
    
    mask_c = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask_c).rectangle([x1, y1, x2, y2], fill=255)
    
    stops = [(0.0, (255, 245, 180)), (0.15, (255, 215, 0)), (0.85, (230, 150, 0)), (1.0, (180, 100, 0))]
    grad = generate_vertical_gradient(WIDTH, h, stops)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    grad_layer.paste(grad, (0, y1))
    layer.paste(grad_layer, (0,0), mask_c)
    draw.rectangle([x1, y1, x2, y2], outline=(255, 235, 120, 255), width=3)
    
    draw.text((cx, cy-2), title_text.upper(), font=font, fill=(255, 224, 102, 255), anchor="mm") 
    draw.text((cx, cy-5), title_text.upper(), font=font, fill=(58, 5, 0, 255), anchor="mm")
    
    shadow = layer.copy().filter(ImageFilter.GaussianBlur(15))
    shadow_data = np.array(shadow)
    shadow_data[..., :3] = 0
    final = Image.fromarray(shadow_data)
    final.alpha_composite(layer)
    return final

def pre_render_tight_hero_text(text):
    font = load_font("hero", 320)
    temp_draw = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    tw, th = max(10, bbox[2] - bbox[0] + 120), max(10, bbox[3] - bbox[1] + 120)
    
    img = Image.new("RGBA", (tw, th), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    cx, cy = tw // 2, th // 2
    
    shadow = Image.new("RGBA", (tw, th), (0,0,0,0))
    ImageDraw.Draw(shadow).text((cx, cy + 20), text, font=font, fill=(0, 0, 0, 240), anchor="mm")
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(15)))
    
    for i in range(12, 0, -1):
        draw.text((cx, cy + i), text, font=font, fill=(70, 15, 0, 255), anchor="mm")
        
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).text((cx, cy), text, font=font, fill=255, anchor="mm")
    
    stops = [(0.0, (255, 255, 230)), (0.2, (255, 220, 0)), (0.7, (255, 160, 0)), (1.0, (180, 60, 0))]
    grad = generate_vertical_gradient(tw, th, stops)
    img.paste(grad, (0, 0), mask)
    draw.text((cx, cy), text, font=font, fill=None, outline=(255, 240, 150, 255), stroke_width=3, anchor="mm")
    return img

def pre_render_grid_card(text, is_small=False):
    w, h = (385, 110) if is_small else (760, 160)
    layer = Image.new("RGBA", (w, h), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle([0, 0, w, h], radius=15, fill=(15, 5, 20, 240), outline=(255, 215, 0, 200), width=3)
    draw.rounded_rectangle([3, 3, w-3, h-3], radius=12, outline=(255, 255, 255, 50), width=1)
    
    cx, cy = w // 2, h // 2 - 5
    font = load_font("hero", 80 if is_small else 95)
    draw.text((cx, cy + 5), text, font=font, fill=(0, 0, 0, 255), anchor="mm")
    draw.text((cx, cy), text, font=font, fill=(255, 250, 240, 255), anchor="mm")
    return layer

# ==========================================
# 4. VIDEO RENDERING ENGINES
# ==========================================
def render_bang_video(theme, prize_heading, item, lottery_title, out_path, base_dur, impact_time_override=None, progress_cb=None):
    audio_file = out_path.replace(".mp4", ".wav")
    audio_dur = get_audio_duration(audio_file)
    
    calc_dur = max(audio_dur + base_dur if audio_dur > 0 else 10.0, 6.0)
    total_frames = int(FPS * calc_dur)
    
    impact_time = impact_time_override if (impact_time_override and impact_time_override > 0) else (1.0 if audio_dur == 0 else min(2.5, audio_dur * 0.4))
    
    bg_asset = pre_render_background(theme)
    
    ticket_num = item
    district = "KERALA"
    dist_match = re.search(r'\((.*?)\)', item)
    if dist_match:
        district = dist_match.group(1).upper()
        ticket_num = item.replace(dist_match.group(0), "").strip()

    hero_asset = pre_render_tight_hero_text(ticket_num)
    orig_tw, orig_th = hero_asset.size
    ribbon_asset = pre_render_ribbon_bang(prize_heading)
    glass_asset = pre_render_glass_card(district)
    
    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    confetti = []
    confetti_triggered = False
    
    temp_draw = ImageDraw.Draw(Image.new("RGBA", (1,1)))
    bbox_glass = temp_draw.textbbox((0, 0), district, font=load_font("black", 85))
    box_w = max(920, (bbox_glass[2] - bbox_glass[0]) + 160)
    glass_bounds = [(WIDTH // 2) - (box_w // 2), 780, (WIDTH // 2) + (box_w // 2), 1000]
    
    bbox_ribbon = temp_draw.textbbox((0, 0), prize_heading.upper(), font=load_font("extrabold", 44))
    ribbon_w = max(1040, (bbox_ribbon[2] - bbox_ribbon[0]) + 120)
    rx = (ribbon_w // 2) - 40
    
    box_glitters = [
        {'x': glass_bounds[0], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': glass_bounds[2], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': glass_bounds[0], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.18},
        {'x': glass_bounds[2], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.14},
        {'x': WIDTH//2 - rx, 'y': 310 - 50, 'phase': random.uniform(0, 6), 'speed': 0.10},
        {'x': WIDTH//2 + rx, 'y': 310 - 50, 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': WIDTH//2 - rx, 'y': 310 + 50, 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': WIDTH//2 + rx, 'y': 310 + 50, 'phase': random.uniform(0, 6), 'speed': 0.17},
    ]

    # Pre-render static base background
    base_bg = bg_asset.copy()
    b_draw = ImageDraw.Draw(base_bg)
    b_draw.text((WIDTH//2, 90), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, 255), anchor="mm")
    b_draw.text((WIDTH//2, 165), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, 255), anchor="mm")
    base_bg.alpha_composite(ribbon_asset)

    for frame in range(total_frames):
        time_sec = frame / FPS
        canvas = base_bg.copy()

        shake_dx, shake_dy = 0, 0
        if time_sec > (impact_time - 0.2):
            slide = ease_out_expo(min((time_sec - (impact_time - 0.2)) / 0.3, 1.0))
            temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            temp.paste(glass_asset, (0, int(150 * (1 - slide))))
            canvas.alpha_composite(temp)

            hp = min((time_sec - (impact_time - 0.2)) / 0.2, 1.0)
            scale = 2.5 - (ease_out_expo(hp) * 1.5)
            nw, nh = max(10, int(orig_tw * scale)), max(10, int(orig_th * scale))
            scaled_hero = hero_asset.resize((nw, nh), Image.Resampling.BILINEAR)
            canvas.paste(scaled_hero, (WIDTH // 2 - nw // 2, 570 - nh // 2), scaled_hero)

            if time_sec >= impact_time:
                if not confetti_triggered:
                    confetti_triggered = True
                    for _ in range(200):
                        angle = random.uniform(0, 2*math.pi)
                        speed = random.uniform(12, 45)
                        confetti.append({'x': WIDTH//2, 'y': 570, 'vx': math.cos(angle)*speed, 'vy': math.sin(angle)*speed-15, 'col': random.choice([(255,215,0), (0,212,255), (255,0,150), (255,255,255)]), 'size': random.randint(4, 12), 'life': 1.0})

                frames_since = int(frame - (impact_time * FPS))
                if frames_since < 5:
                    intensity = int(20 - (frames_since * 4))
                    shake_dx, shake_dy = random.randint(-intensity, intensity), random.randint(-intensity, intensity)

        if time_sec >= impact_time:
            c_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            c_draw = ImageDraw.Draw(c_layer)
            for p in confetti:
                if p['life'] > 0:
                    p['x'] += p['vx']
                    p['y'] += p['vy']
                    p['vy'] += 2.0
                    p['life'] -= 0.025
                    s = int(p['size'])
                    c_draw.rectangle([int(p['x'])-s, int(p['y'])-s//2, int(p['x'])+s, int(p['y'])+s//2], fill=p['col']+(int(255*max(p['life'], 0)),))
            canvas.alpha_composite(c_layer)

            glitter_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            g_draw = ImageDraw.Draw(glitter_layer)
            for g in box_glitters:
                g['phase'] += g['speed']
                pulse = (math.sin(g['phase']) + 1) / 2
                s = int(5 + 20 * pulse)
                g_op = int(50 + 205 * pulse)
                g_draw.line([(g['x']-s, g['y']), (g['x']+s, g['y'])], fill=(255, 235, 100, g_op), width=3)
                g_draw.line([(g['x'], g['y']-s), (g['x'], g['y']+s)], fill=(255, 235, 100, g_op), width=3)
                g_draw.ellipse([g['x']-4, g['y']-4, g['x']+4, g['y']+4], fill=(255, 255, 255, g_op))
            canvas.alpha_composite(glitter_layer.filter(ImageFilter.GaussianBlur(2)))

        final_frame = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,255))
        final_frame.paste(canvas, (int(shake_dx), int(shake_dy)))
        out.write(cv2.cvtColor(np.array(final_frame), cv2.COLOR_RGBA2BGR))

        if progress_cb and frame % 25 == 0:
            try: progress_cb(frame + 1, total_frames)
            except Exception: pass

    out.release()
    if progress_cb:
        try: progress_cb(total_frames, total_frames)
        except Exception: pass
    gc.collect()

    v_filters = []
    if ENABLE_TRANSITIONS and TRANSITION_FADE_DURATION > 0:
        fade_out_st = max(0.0, calc_dur - TRANSITION_FADE_DURATION)
        v_filters.append(f"fade=t=in:st=0:d={TRANSITION_FADE_DURATION}")
        v_filters.append(f"fade=t=out:st={fade_out_st}:d={TRANSITION_FADE_DURATION}")
    v_filter_str = ",".join(v_filters) if v_filters else "null"

    cmd = ["ffmpeg", "-y", "-threads", "2", "-i", raw_path]
    if os.path.exists(audio_file) and os.path.exists(BANG_AUDIO_BGM):
        delay_ms = int(impact_time * 1000)
        cmd.extend([
            "-i", audio_file, "-i", BANG_AUDIO_BGM, "-filter_complex", 
            f"[0:v]{v_filter_str}[vout];"
            f"[1:a]aformat=channel_layouts=stereo:sample_rates=44100,volume=1.0,apad[a1];"
            f"[2:a]aformat=channel_layouts=stereo:sample_rates=44100,volume=0.25,adelay={delay_ms}|{delay_ms}[a2];"
            f"[a1][a2]amix=inputs=2:duration=first:dropout_transition=0,atrim=0:{calc_dur}[aout]", 
            "-map", "[vout]", "-map", "[aout]"
        ])
    elif os.path.exists(audio_file):
        cmd.extend([
            "-i", audio_file, "-filter_complex",
            f"[0:v]{v_filter_str}[vout];"
            f"[1:a]aformat=channel_layouts=stereo:sample_rates=44100,apad,atrim=0:{calc_dur}[aout]",
            "-map", "[vout]", "-map", "[aout]"
        ])
    else:
        cmd.extend([
            "-filter_complex", f"[0:v]{v_filter_str}[vout]",
            "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:d={calc_dur}",
            "-map", "[vout]", "-map", "1:a"
        ])
        
    cmd.extend(["-vcodec", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)

def render_scroll_video(theme, prize_heading, numbers_list, lottery_title, out_path, base_dur, is_4col, end_delay, start_delay_override=None, progress_cb=None):
    audio_file = out_path.replace(".mp4", ".wav")
    audio_dur = get_audio_duration(audio_file)
    
    start_delay = start_delay_override if (start_delay_override and start_delay_override > 0) else (audio_dur if audio_dur > 0 else 2.0)
    calc_dur = start_delay + base_dur
    total_frames = int(FPS * calc_dur)
    
    cols = 4 if is_4col else 2
    bg_asset = pre_render_background(theme)
    ribbon_asset = pre_render_ribbon_scroll(prize_heading)

    rows = math.ceil(len(numbers_list) / cols)
    max_scroll = max(0, rows * (150 if is_4col else 200) - 400)
    total_canvas_h = max(HEIGHT, 440 + (rows * (150 if is_4col else 200)) + 600)
    
    giant_canvas = Image.new("RGBA", (WIDTH, total_canvas_h), (0,0,0,0))
    for i, num in enumerate(numbers_list):
        col, row = i % cols, i // cols
        c_x = [240, 720, 1200, 1680][col] if is_4col else (540 if col == 0 else 1380)
        c_y = 440 + (row * (150 if is_4col else 200))
        card = pre_render_grid_card(num, is_small=is_4col)
        cw, ch = card.size
        giant_canvas.paste(card, (int(c_x - cw//2), int(c_y - ch//2)), card)

    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    m_draw = ImageDraw.Draw(mask)
    fade_start, fade_end = 360, 420
    for y in range(fade_start, fade_end):
        m_draw.line([(0, y), (WIDTH, y)], fill=int(255 * (y - fade_start) / (fade_end - fade_start)))
    m_draw.rectangle([0, fade_end, WIDTH, HEIGHT], fill=255)

    # Pre-render static base background to eliminate per-frame font and ribbon overhead
    base_bg = bg_asset.copy()
    b_draw = ImageDraw.Draw(base_bg)
    b_draw.text((WIDTH//2, 60), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, 255), anchor="mm")
    b_draw.text((WIDTH//2, 135), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, 255), anchor="mm")
    base_bg.alpha_composite(ribbon_asset)

    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))

    for frame in range(total_frames):
        time_sec = frame / FPS
        canvas = base_bg.copy()

        scroll_start = start_delay
        scroll_end = max(scroll_start + 0.5, calc_dur - end_delay)
        
        crop_y = 0
        if scroll_start < time_sec < scroll_end:
            progress = (time_sec - scroll_start) / (scroll_end - scroll_start)
            crop_y = int(max_scroll * ease_in_out_cubic(progress))
        elif time_sec >= scroll_end:
            crop_y = max_scroll

        cards_layer = giant_canvas.crop((0, crop_y, WIDTH, crop_y + HEIGHT))
        # Fast native C alpha channel multiplication
        cards_layer.putalpha(ImageChops.multiply(cards_layer.getchannel('A'), mask))
        canvas.alpha_composite(cards_layer)

        out.write(cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR))

        if progress_cb and frame % 30 == 0:
            try: progress_cb(frame + 1, total_frames)
            except Exception: pass

    out.release()
    if progress_cb:
        try: progress_cb(total_frames, total_frames)
        except Exception: pass
    gc.collect()

    v_filters = []
    if ENABLE_TRANSITIONS and TRANSITION_FADE_DURATION > 0:
        fade_out_st = max(0.0, calc_dur - TRANSITION_FADE_DURATION)
        v_filters.append(f"fade=t=in:st=0:d={TRANSITION_FADE_DURATION}")
        v_filters.append(f"fade=t=out:st={fade_out_st}:d={TRANSITION_FADE_DURATION}")
    v_filter_str = ",".join(v_filters) if v_filters else "null"

    # Direct Clean Voiceover Mixing without Background Music
    cmd = ["ffmpeg", "-y", "-threads", "2", "-i", raw_path]
    if os.path.exists(audio_file):
        cmd.extend([
            "-i", audio_file, "-filter_complex", 
            f"[0:v]{v_filter_str}[vout];"
            f"[1:a]aformat=channel_layouts=stereo:sample_rates=44100,volume=1.0,apad,atrim=0:{calc_dur}[aout]", 
            "-map", "[vout]", "-map", "[aout]"
        ])
    else:
        cmd.extend([
            "-filter_complex", f"[0:v]{v_filter_str}[vout]",
            "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:d={calc_dur}",
            "-map", "[vout]", "-map", "1:a"
        ])
        
    cmd.extend(["-vcodec", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)

# ==========================================
# 5. BOT PIPELINE & FFMPEG STITCHING
# ==========================================

def compress_and_combine(video_files, final_output):
    if not video_files: return
    if len(video_files) == 1:
        shutil.copy(video_files[0], final_output)
        return

    # Normalized sequential concatenation with Reset Timestamps (Fixes freeze & audio loss)
    cmd = ["ffmpeg", "-y", "-threads", "2"]
    filter_str = ""
    for i, vid in enumerate(video_files):
        cmd.extend(["-i", vid])
        # setpts and asetpts reset the clock to 0.0 for every segment, preventing freezes and audio dropouts
        filter_str += (
            f"[{i}:v:0]setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
            f"[{i}:a:0]asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
        )
        
    concat_inputs = "".join([f"[v{i}][a{i}]" for i in range(len(video_files))])
    filter_complex = f"{filter_str}{concat_inputs}concat=n={len(video_files)}:v=1:a=1[v][a]"
    
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        final_output
    ])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for vid in video_files:
        if os.path.exists(vid):
            os.remove(vid)

async def execute_result_pipeline(app, chat_id, target_url):
    msg = await app.send_message(chat_id, "🔎 **Fetching lottery draw data...**")
    
    text_msg, tts_txt, tts_dict, draw_date, prizes, prize_headings, lottery_title = parse_lottery_result_page(target_url)
    if not prizes:
        return await msg.edit_text("❌ Scraping failed or no data found. Results may not be fully published.")

    await msg.delete()
    chunks = [text_msg[i:i+3500] for i in range(0, len(text_msg), 3500)]
    for chunk in chunks:
        await app.send_message(chat_id, chunk)
        await asyncio.sleep(0.4)

    # Broadcast scraped text result to Channel
    await broadcast_to_channel(app, text=text_msg)

    if tts_txt and tts_txt.strip():
        tts_file = io.BytesIO(tts_txt.encode('utf-8'))
        tts_file.name = f"TTS_{draw_date}.txt"
        await app.send_document(
            chat_id=chat_id,
            document=tts_file,
            caption=f"🗣️ **Malayalam Pronunciation File for TTS**\n📅 `{draw_date}`"
        )
        
        # Broadcast TTS file to Channel
        tts_file.seek(0)
        await broadcast_to_channel(app, document=tts_file, caption=f"🗣️ **Malayalam TTS Script** • `{draw_date}`")
        await asyncio.sleep(0.4)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"vy_{draw_date}"),
            InlineKeyboardButton("❌ No", callback_data=f"vn_{draw_date}")
        ]
    ])
    await app.send_message(chat_id, "🎬 **Do you want to generate the videos?**", reply_markup=keyboard)

USER_VIDEOS = {}

# ==========================================
# 6. ASYNC PYROFORK BOT
# ==========================================
async def run_pyrofork_bot():
    GLOBAL_STATE.main_event_loop = asyncio.get_running_loop()
    try:
        app = Client(
            "lottery_bot",
            api_id=int(st.secrets["API_ID"]),
            api_hash=str(st.secrets["API_HASH"]),
            bot_token=str(st.secrets["BOT_TOKEN"]),
            in_memory=True
        )

        @app.on_message(filters.command("start") & filters.private)
        async def handle_start(client, message):
            welcome = (
                "👋 **Welcome to Kerala Lottery Video Generator Bot!** ✨\n\n"
                "**🌟 Available Commands:**\n"
                "• 🚀 `/generate` - Fetch today's result & render pipeline\n"
                "• 📅 `/gencustom` - Select from last 10 draw dates\n"
                "• 🖼️ `/genthumb` - Generate YouTube thumbnail for a draw date\n"
                "• 🔗 `/combine` - Stitch uploaded videos together\n"
                "• ℹ️ `/start` - Show this menu"
            )
            await message.reply_text(welcome)

        @app.on_message(filters.command("generate") & filters.private)
        async def handle_generate(client, message):
            draws = fetch_last_10_draws()
            if not draws: return await message.reply_text("❌ Could not retrieve draw list.")
            await execute_result_pipeline(app, message.chat.id, draws[0]['url'])

        @app.on_message(filters.command("gencustom") & filters.private)
        async def handle_gencustom(client, message):
            draws = fetch_last_10_draws()
            text_lines = ["📅 **Select a date:**\n"]
            buttons = []
            for item in draws:
                d_str = item['date']
                buttons.append([InlineKeyboardButton(f"📅 {d_str} | {item['title'][:20]}", callback_data=f"get_{d_str}")])
            await message.reply_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))

        @app.on_message(filters.command("genthumb") & filters.private)
        async def handle_genthumb(client, message):
            draws = fetch_last_10_draws()
            text_lines = ["🖼️ **Select a draw date to generate Thumbnail:**\n"]
            buttons = []
            for item in draws:
                d_str = item['date']
                buttons.append([InlineKeyboardButton(f"📅 {d_str} | {item['title'][:20]}", callback_data=f"th_{d_str}")])
            await message.reply_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))

        @app.on_callback_query(filters.regex(r"^th_(\d{2}-\d{2}-\d{4})"))
        async def handle_thumb_callback(client, callback_query):
            target_date = callback_query.matches[0].group(1)
            await callback_query.answer()
            status_msg = await callback_query.message.reply_text(f"🎨 **Generating YouTube Thumbnail for `{target_date}`...**")
            
            if target_date in GLOBAL_STATE.scraped_cache:
                c_data = GLOBAL_STATE.scraped_cache[target_date]
                lottery_title = c_data["lottery_title"]
            else:
                draws = fetch_last_10_draws()
                target_entry = next((d for d in draws if d['date'] == target_date), None)
                target_url = target_entry['url'] if target_entry else (draws[0]['url'] if draws else "")
                if target_url:
                    _, _, _, _, _, _, lottery_title = parse_lottery_result_page(target_url)
                else:
                    lottery_title = "KERALA LOTTERY"
            
            thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{target_date}.png")
            await asyncio.to_thread(thumbnail.generate_thumbnail, lottery_title, target_date, thumb_path)
            
            if os.path.exists(thumb_path):
                await client.send_photo(
                    chat_id=callback_query.message.chat.id,
                    photo=thumb_path,
                    caption=f"🖼️ **YouTube Thumbnail** • `{lottery_title}` (`{target_date}`)"
                )
                await broadcast_to_channel(
                    client,
                    photo_path=thumb_path,
                    caption=f"🖼️ **YouTube Thumbnail** • `{lottery_title}` (`{target_date}`)"
                )
            await status_msg.delete()

        @app.on_callback_query(filters.regex(r"^get_(\d{2}-\d{2}-\d{4})"))
        async def handle_get_callback(client, callback_query):
            await callback_query.answer()
            target_date = callback_query.matches[0].group(1)
            draws = fetch_last_10_draws()
            target_entry = next((d for d in draws if d['date'] == target_date), None)
            target_url = target_entry['url'] if target_entry else (draws[0]['url'] if draws else "")
            if target_url:
                await execute_result_pipeline(app, callback_query.message.chat.id, target_url)
            else:
                await callback_query.message.reply_text("❌ Could not locate draw post URL.")

        @app.on_callback_query(filters.regex(r"^vn_"))
        async def handle_video_no(client, callback_query):
            await callback_query.message.delete()

        @app.on_callback_query(filters.regex(r"^vy_(.*)"))
        async def handle_video_yes(client, callback_query):
            draw_date = callback_query.matches[0].group(1)
            tier_names = ["Intro", "1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]
            
            buttons = []
            for i, name in enumerate(tier_names):
                buttons.append([
                    InlineKeyboardButton(f"🎥 {name} Only", callback_data=f"rs_{i}_{draw_date}"),
                    InlineKeyboardButton(f"⏭️ Up to {name}", callback_data=f"ru_{i}_{draw_date}")
                ])
            buttons.append([InlineKeyboardButton("🔀 Custom Range", callback_data=f"rr_{draw_date}")])
            
            await callback_query.message.edit_text("🎛️ **Select Video Generation Mode:**", reply_markup=InlineKeyboardMarkup(buttons))

        async def render_and_process_tier(client, chat_id, p_name, engine, dur, is_4c, theme, end_delay, tts_entry, prizes, prize_headings, lottery_title, draw_date):
            audio_path = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}.wav")
            out_path = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}.mp4")
            part1_dur = 0.0

            GLOBAL_STATE.set_status(f"Audio Generation ({p_name})", 0.1, f"Synthesizing voiceover for {p_name}...")
            GLOBAL_STATE.log(f"Starting pipeline for {p_name}...")

            if tts_entry:
                status_msg = await client.send_message(chat_id, f"🗣️ **Generating Audio for {p_name}...**")
                try:
                    if isinstance(tts_entry, dict):
                        h_text = tts_entry.get("header", "")
                        n_text = tts_entry.get("numbers", "")
                        p1_file = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}_p1.wav")
                        p2_file = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}_p2.wav")

                        if h_text:
                            await generate_cartesia_audio(h_text, p1_file)
                            part1_dur = get_audio_duration(p1_file)

                        if n_text:
                            await generate_cartesia_audio(n_text, p2_file)

                        if os.path.exists(p1_file) and os.path.exists(p2_file):
                            concat_wav_files(p1_file, p2_file, audio_path)
                            for f in [p1_file, p2_file]:
                                if os.path.exists(f): os.remove(f)
                        elif os.path.exists(p1_file):
                            if os.path.exists(audio_path): os.remove(audio_path)
                            os.rename(p1_file, audio_path)
                    else:
                        await generate_cartesia_audio(str(tts_entry), audio_path)

                    if os.path.exists(audio_path):
                        await client.send_audio(chat_id=chat_id, audio=audio_path, caption=f"🔊 **{p_name} Voiceover**\n📅 `{draw_date}`")
                        await broadcast_to_channel(client, audio_path=audio_path, caption=f"🔊 **{p_name} Voiceover**\n📅 `{draw_date}`")
                except Exception as e:
                    GLOBAL_STATE.log(f"Audio error on {p_name}: {e}")
                finally:
                    await status_msg.delete()

            status_msg = await client.send_message(chat_id, f"🎬 **Rendering {p_name} Video...** [0%]")
            last_ui_update = [0.0]

            def on_frame_progress(current, total):
                pct = int((current / total) * 100)
                GLOBAL_STATE.set_status(f"Rendering {p_name}", current / total, f"Frame {current}/{total} ({pct}%)")
                
                now = time.time()
                if now - last_ui_update[0] > 3.0 and GLOBAL_STATE.main_event_loop:
                    last_ui_update[0] = now
                    try:
                        asyncio.run_coroutine_threadsafe(
                            status_msg.edit_text(f"🎬 **Rendering {p_name} Video...** [{current}/{total} frames - {pct}%]"),
                            GLOBAL_STATE.main_event_loop
                        )
                    except Exception:
                        pass

            try:
                if engine == "intro":
                    await asyncio.to_thread(intro.generate_video, out_path)
                else:
                    full_heading = prize_headings.get(p_name, p_name)
                    if engine == "bang":
                        bang_impact = part1_dur if part1_dur > 0 else None
                        await asyncio.to_thread(render_bang_video, theme, full_heading, prizes[p_name][0], lottery_title, out_path, dur, bang_impact, on_frame_progress)
                    else:
                        scroll_start = part1_dur if part1_dur > 0 else None
                        await asyncio.to_thread(render_scroll_video, theme, full_heading, prizes[p_name], lottery_title, out_path, dur, is_4c, end_delay, scroll_start, on_frame_progress)

                if os.path.exists(out_path):
                    await status_msg.edit_text(f"🚀 **Uploading {p_name} Video...**")
                    await client.send_video(chat_id=chat_id, video=out_path, caption=f"🏆 **{p_name}** - `{draw_date}`")
                    await broadcast_to_channel(client, video_path=out_path, caption=f"🏆 **{p_name}** - `{draw_date}`")
            except Exception as e:
                GLOBAL_STATE.log(f"Video render error for {p_name}: {e}")
            finally:
                await status_msg.delete()

            return out_path if os.path.exists(out_path) else None

        @app.on_callback_query(filters.regex(r"^(rs|ru)_(\d+)_(.*)"))
        async def handle_render_action(client, callback_query):
            action, tier_idx, draw_date = callback_query.matches[0].group(1), int(callback_query.matches[0].group(2)), callback_query.matches[0].group(3)
            await callback_query.message.edit_text("🔎 **Fetching draw results for rendering...**")
            
            # Always fetch fresh data on render to ensure real-time live draws are captured
            if draw_date in GLOBAL_STATE.scraped_cache:
                c_data = GLOBAL_STATE.scraped_cache[draw_date]
                tts_dict = c_data["tts_dict"]
                prizes = c_data["prizes"]
                prize_headings = c_data["prize_headings"]
                lottery_title = c_data["lottery_title"]
            else:
                draws = fetch_last_10_draws()
                target_entry = next((d for d in draws if d['date'] == draw_date), None)
                target_url = target_entry['url'] if target_entry else (draws[0]['url'] if draws else "")
                if target_url:
                    _, _, tts_dict, draw_date, prizes, prize_headings, lottery_title = parse_lottery_result_page(target_url)
                else:
                    return await callback_query.message.edit_text("❌ Could not locate draw post URL.")
            
            tier_config = [
                ("Intro", "intro", 0, False, "none", 0),
                ("1st Prize", "bang", DURATION_1ST_PRIZE, False, "purple", 0),
                ("Consolation Prize", "scroll", DURATION_CONSOLATION, False, "blue", CONSOLATION_END_DELAY),
                ("2nd Prize", "bang", DURATION_2ND_PRIZE, False, "silver", 0),
                ("3rd Prize", "bang", DURATION_3RD_PRIZE, False, "gold", 0),
                ("4th Prize", "scroll", DURATION_4TH_PRIZE, False, "blue", PRIZE_4TH_END_DELAY),
                ("5th Prize", "scroll", DURATION_5TH_PRIZE, False, "blue", PRIZE_5TH_END_DELAY),
                ("6th Prize", "scroll", DURATION_6TH_PRIZE, False, "blue", PRIZE_6TH_END_DELAY),
                ("7th Prize", "scroll", DURATION_7TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY),
                ("8th Prize", "scroll", DURATION_8TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY),
                ("9th Prize", "scroll", DURATION_9TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY)
            ]

            video_files = []
            video_durations_map = {}
            tiers_to_render = [tier_config[tier_idx]] if action == "rs" else tier_config[:tier_idx + 1]
            await callback_query.message.delete()

            for p_name, engine, dur, is_4c, theme, end_delay in tiers_to_render:
                if engine == "intro" or (p_name in prizes and prizes[p_name]):
                    tts_entry = tts_dict.get(p_name)
                    vid_out = await render_and_process_tier(
                        client, callback_query.message.chat.id, p_name, engine, dur, is_4c, theme, end_delay,
                        tts_entry, prizes, prize_headings, lottery_title, draw_date
                    )
                    if vid_out:
                        video_files.append(vid_out)
                        video_durations_map[p_name] = get_video_duration(vid_out)

            # Generate and Send 1-Tap Copyable YouTube Metadata Package with Prize Numbers in Timestamps
            title_1, title_2, yt_desc, yt_tags = generate_youtube_package(lottery_title, draw_date, video_durations_map, prizes)
            await send_yt_metadata_package(client, callback_query.message.chat.id, title_1, title_2, yt_desc, yt_tags)

            if action == "ru" and len(video_files) > 1:
                GLOBAL_STATE.set_status("Final Stitching", 0.95, f"Combining {len(video_files)} video segments...")
                status_msg = await client.send_message(callback_query.message.chat.id, "🗜️ **Combining selected videos...**")
                await asyncio.to_thread(compress_and_combine, video_files, FINAL_OUTPUT_VIDEO)
                await status_msg.edit_text("🚀 **Uploading final combined video...**")
                await client.send_video(chat_id=callback_query.message.chat.id, video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Final Combined Broadcast**\n📅 `{draw_date}`")
                await broadcast_to_channel(client, video_path=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Final Combined Broadcast**\n📅 `{draw_date}`")
                await status_msg.delete()
                if os.path.exists(FINAL_OUTPUT_VIDEO): os.remove(FINAL_OUTPUT_VIDEO)
                GLOBAL_STATE.set_status("Idle", 1.0, "Ready")

        @app.on_callback_query(filters.regex(r"^rr_(.*)"))
        async def handle_range_request(client, callback_query):
            draw_date = callback_query.matches[0].group(1)
            await callback_query.message.delete()
            await client.send_message(
                callback_query.message.chat.id,
                f"🔀 **Custom Range for {draw_date}**\n\nReply to this message with your range.\nUse `i` for Intro, `c` for Consolation, and `1-9` for prizes.\n\nExamples:\n`7-9` (7th to 9th)\n`i-2` (Intro to 2nd)",
                reply_markup=ForceReply(selective=True)
            )

        @app.on_message(filters.reply & filters.private)
        async def handle_range_reply(client, message):
            if not message.reply_to_message.text or "Custom Range for" not in message.reply_to_message.text: return
            draw_date = re.search(r"for (\d{2}-\d{2}-\d{4})", message.reply_to_message.text).group(1)
            text = message.text.lower().replace(" ", "")
            if "-" not in text: return await message.reply_text("❌ Invalid format.")

            start_str, end_str = text.split("-")[0], text.split("-")[1]
            idx_map = {'i': 0, '1': 1, 'c': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10}
            if start_str not in idx_map or end_str not in idx_map: return await message.reply_text("❌ Invalid keys.")
            start_idx, end_idx = idx_map[start_str], idx_map[end_str]

            await message.reply_text("🔎 **Fetching data for custom range rendering...**")
            
            if draw_date in GLOBAL_STATE.scraped_cache:
                c_data = GLOBAL_STATE.scraped_cache[draw_date]
                tts_dict = c_data["tts_dict"]
                prizes = c_data["prizes"]
                prize_headings = c_data["prize_headings"]
                lottery_title = c_data["lottery_title"]
            else:
                draws = fetch_last_10_draws()
                target_entry = next((d for d in draws if d['date'] == draw_date), None)
                target_url = target_entry['url'] if target_entry else (draws[0]['url'] if draws else "")
                if target_url:
                    _, _, tts_dict, draw_date, prizes, prize_headings, lottery_title = parse_lottery_result_page(target_url)
                else:
                    return await message.reply_text("❌ Could not locate draw post URL.")
            
            tier_config = [
                ("Intro", "intro", 0, False, "none", 0),
                ("1st Prize", "bang", DURATION_1ST_PRIZE, False, "purple", 0),
                ("Consolation Prize", "scroll", DURATION_CONSOLATION, False, "blue", CONSOLATION_END_DELAY),
                ("2nd Prize", "bang", DURATION_2ND_PRIZE, False, "silver", 0),
                ("3rd Prize", "bang", DURATION_3RD_PRIZE, False, "gold", 0),
                ("4th Prize", "scroll", DURATION_4TH_PRIZE, False, "blue", PRIZE_4TH_END_DELAY),
                ("5th Prize", "scroll", DURATION_5TH_PRIZE, False, "blue", PRIZE_5TH_END_DELAY),
                ("6th Prize", "scroll", DURATION_6TH_PRIZE, False, "blue", PRIZE_6TH_END_DELAY),
                ("7th Prize", "scroll", DURATION_7TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY),
                ("8th Prize", "scroll", DURATION_8TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY),
                ("9th Prize", "scroll", DURATION_9TH_PRIZE, True, "blue", PRIZE_7_8_9_END_DELAY)
            ]

            video_files = []
            video_durations_map = {}
            for p_name, engine, dur, is_4c, theme, end_delay in tier_config[start_idx : end_idx + 1]:
                if engine == "intro" or (p_name in prizes and prizes[p_name]):
                    tts_entry = tts_dict.get(p_name)
                    vid_out = await render_and_process_tier(
                        client, message.chat.id, p_name, engine, dur, is_4c, theme, end_delay,
                        tts_entry, prizes, prize_headings, lottery_title, draw_date
                    )
                    if vid_out:
                        video_files.append(vid_out)
                        video_durations_map[p_name] = get_video_duration(vid_out)

            # Generate and Send 1-Tap Copyable YouTube Metadata Package with Prize Numbers in Timestamps
            title_1, title_2, yt_desc, yt_tags = generate_youtube_package(lottery_title, draw_date, video_durations_map, prizes)
            await send_yt_metadata_package(client, message.chat.id, title_1, title_2, yt_desc, yt_tags)

            if len(video_files) > 1:
                status_msg = await client.send_message(message.chat.id, "🗜️ **Combining custom range...**")
                await asyncio.to_thread(compress_and_combine, video_files, FINAL_OUTPUT_VIDEO)
                await status_msg.edit_text("🚀 **Uploading combined sequence...**")
                await client.send_video(chat_id=message.chat.id, video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Range ({text})**\n📅 `{draw_date}`")
                await broadcast_to_channel(client, video_path=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Range ({text})**\n📅 `{draw_date}`")
                await status_msg.delete()
                if os.path.exists(FINAL_OUTPUT_VIDEO): os.remove(FINAL_OUTPUT_VIDEO)

        @app.on_message(filters.video & filters.private)
        async def handle_video_receive(client, message):
            chat_id = message.chat.id
            if chat_id not in USER_VIDEOS: USER_VIDEOS[chat_id] = []
            msg = await message.reply_text("⬇️ Downloading video piece...")
            file_path = os.path.join(DOWNLOAD_DIR, f"manual_{chat_id}_{len(USER_VIDEOS[chat_id])}.mp4")
            await message.download(file_name=file_path)
            USER_VIDEOS[chat_id].append(file_path)
            await msg.edit_text(f"✅ **Video #{len(USER_VIDEOS[chat_id])} saved!**\nType `/combine` to stitch.")

        @app.on_message(filters.command("combine") & filters.private)
        async def handle_combine(client, message):
            chat_id = message.chat.id
            if chat_id not in USER_VIDEOS or len(USER_VIDEOS[chat_id]) == 0: return await message.reply_text("❌ Send video files first!")
            status = await message.reply_text("🗜️ **Combining seamlessly...**")
            out_path = os.path.join(DOWNLOAD_DIR, f"manual_combined_{chat_id}.mp4")
            await asyncio.to_thread(compress_and_combine, USER_VIDEOS[chat_id], out_path)
            await status.edit_text("🚀 **Uploading...**")
            await client.send_video(chat_id, out_path)
            await broadcast_to_channel(client, video_path=out_path, caption="🎟️ **Manual Stitched Video**")
            await status.delete()
            if os.path.exists(out_path): os.remove(out_path)
            USER_VIDEOS[chat_id] = []

        await app.start()
        GLOBAL_STATE.log("Bot Started Successfully.")
        await asyncio.Event().wait()
    except Exception as e:
        GLOBAL_STATE.log(f"CRITICAL ERROR: Bot thread crashed: {e}")
    finally:
        if 'app' in locals() and app.is_initialized: await app.stop()

# ==========================================
# 7. STREAMLIT DASHBOARD & LIVE TELEMETRY
# ==========================================
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_pyrofork_bot())
        except Exception as e:
            GLOBAL_STATE.log(f"Async loop crashed: {e}")
    threading.Thread(target=run_async_loop, daemon=True).start()

start_bot_thread()

st.set_page_config(page_title="Kerala Lottery Engine", page_icon="🎬", layout="wide")
st.title("🎬 Kerala Lottery Video Production Engine")
st.caption("Active & Connected • Live Frame Telemetry & Multi-Tier Pipeline")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📊 Engine Status")
    st.metric(label="Current Task", value=GLOBAL_STATE.current_status["task"])
    st.progress(GLOBAL_STATE.current_status["progress"])
    st.info(GLOBAL_STATE.current_status["details"])

with col2:
    st.subheader("📜 Live Process Console")
    log_area = st.empty()
    log_area.code("\n".join(GLOBAL_STATE.log_history) if GLOBAL_STATE.log_history else "System ready. Waiting for draw commands...", language="text")
