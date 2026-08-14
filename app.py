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
import numpy as np
import cv2
import subprocess
import concurrent.futures
from datetime import datetime
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# ==========================================
# --- USER CONFIGURATION BLOCK ---
# ==========================================

# 1. SET VIDEO DURATIONS (IN SECONDS)
DURATION_1ST_PRIZE = 10
DURATION_CONSOLATION = 16
DURATION_2ND_PRIZE = 10
DURATION_3RD_PRIZE = 10
DURATION_4TH_PRIZE = 25
DURATION_5TH_PRIZE = 25
DURATION_6TH_PRIZE = 25
DURATION_7TH_PRIZE = 90
DURATION_8TH_PRIZE = 90
DURATION_9TH_PRIZE = 90
DURATION_10TH_PRIZE = 90

# 2. SCROLL SPEED SETTINGS (START AND END DELAYS)
# Lowering total duration + keeping delays the same = FASTER scrolling.

CONSOLATION_START_DELAY = 2.0
CONSOLATION_END_DELAY = 2.0

PRIZE_4TH_START_DELAY = 2.0
PRIZE_4TH_END_DELAY = 2.0

PRIZE_5TH_START_DELAY = 2.0
PRIZE_5TH_END_DELAY = 2.0

PRIZE_6TH_START_DELAY = 2.0
PRIZE_6TH_END_DELAY = 2.0

PRIZE_7_8_9_START_DELAY = 2.0
PRIZE_7_8_9_END_DELAY = 2.0

PRIZE_10TH_START_DELAY = 2.0
PRIZE_10TH_END_DELAY = 2.0

# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "renders")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FINAL_OUTPUT_VIDEO = os.path.join(DOWNLOAD_DIR, "final_combined_lottery.mp4")

FPS = 30
WIDTH, HEIGHT = 1920, 1080

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

# --- HTTP ENGINE ---
try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests as standard_requests
    USE_CURL_CFFI = False

def http_get(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if USE_CURL_CFFI:
        return cffi_requests.get(url, impersonate="chrome")
    return standard_requests.get(url, headers=headers)

# --- MALAYALAM TTS CONVERSION HELPERS ---
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

def to_tts_format(ticket_str: str) -> str:
    match_series = re.match(r'^([A-Z]{2})\s*(\d{6})(.*)$', ticket_str)
    if match_series:
        series, number, extra = match_series.group(1), match_series.group(2), match_series.group(3).strip()
        s_parts = [ALPHA_TO_ML.get(c, c) for c in series]
        n_parts = [DIGITS_TO_ML.get(d, d) for d in number]
        combined = " , ".join(s_parts + n_parts)
        if extra: combined += f" {extra}"
        return combined
    else:
        n_parts = [DIGITS_TO_ML.get(d, d) for d in ticket_str]
        return " , ".join(n_parts)

# ==========================================
# 1. SCRAPING LOGIC
# ==========================================
def fetch_last_10_draws():
    base_url = "https://www.keralalotteries.net/?m=1"
    draws = []
    try:
        res = http_get(base_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.find_all('tr'):
            tds = row.find_all('td')
            if len(tds) >= 2:
                a_tag = row.find('a', href=True)
                date_match = re.search(r'\d{2}-\d{2}-\d{4}', row.get_text())
                if date_match and a_tag:
                    d_str = date_match.group(0)
                    title = tds[1].get_text(strip=True).replace('\n', ' ')
                    title = re.sub(r'\s*Official Result$', '', title, flags=re.IGNORECASE)
                    if not any(d['date'] == d_str for d in draws):
                        draws.append({'date': d_str, 'title': title, 'url': a_tag['href']})
            if len(draws) >= 10: break
        return draws
    except Exception as e:
        print(f"**[LOG]** Error fetching draws: {e}", flush=True)
        return []

def clean_prize_heading(raw_str):
    """Dynamic Regex engine to correctly fetch ANY prize money amount from 1st to 10th."""
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
            return "❌ Could not parse body.", None, None, {}, {}, None

        h1_tag = soup.find('h1', class_='entry-title')
        raw_title = h1_tag.get_text(strip=True) if h1_tag else "KERALA LOTTERY"
        
        clean_match = re.search(r'([A-Za-z\s]+[A-Za-z])\s+([A-Z]{2}-\d{3})', raw_title)
        if clean_match:
            clean_lottery_title = f"{clean_match.group(1).upper()} ({clean_match.group(2)})"
        else:
            clean_lottery_title = re.sub(r'Kerala Lottery Results:|\bOfficial\b|\bResult\b|\bToday\b|\d{2}-\d{2}-\d{4}', '', raw_title, flags=re.IGNORECASE).strip().upper()

        # Flawless Newline Preservation
        for tag in post_body.find_all(['br', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'li', 'table']):
            tag.insert_after('\n')
        
        # We do NOT use strip=True here, because it removes the \n we just injected.
        full_text = post_body.get_text(separator=' ')
        lines = [re.sub(r'\s+', ' ', line).strip() for line in full_text.split('\n') if line.strip()]

        date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', full_text)
        draw_date = date_match.group(1).replace('/', '-') if date_match else "N/A"

        series_match = re.search(r'Today Lottery Series:\s*([A-Z0-9,\s]+)', full_text)
        series_str = series_match.group(1).strip() if series_match else "N/A"

        prize_headers = ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize", "10th Prize"]
        prizes_data = {}
        prize_headings = {}
        current_prize_key = None

        for line in lines:
            if any(sp in line.lower() for sp in ["prize winners are advised to verify", "government gazette", "tomorrow draw details"]): break
            
            matched_header = next((ph for ph in prize_headers if ph.lower() in line.lower()), None)
            if matched_header:
                current_prize_key = matched_header
                if current_prize_key not in prizes_data:
                    prizes_data[current_prize_key] = []
                    prize_headings[current_prize_key] = clean_prize_heading(line)
                continue

            if current_prize_key:
                if (line.startswith("(") and line.endswith(")")) or line in ["...", "---"]: continue
                if current_prize_key in ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line): prizes_data[current_prize_key].append(line)
                else:
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    if four_digits: prizes_data[current_prize_key].extend(four_digits)

        msg_output = [f"🎟️ **{clean_lottery_title}**", f"📅 **Date:** `{draw_date}`", f"🔢 **Series:** `{series_str}`", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        prize_order = [("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"), ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣"), ("7th Prize", "7️⃣"), ("8th Prize", "8️⃣"), ("9th Prize", "9️⃣"), ("10th Prize", "🔟")]

        for p_key, emoji in prize_order:
            if p_key in prizes_data and prizes_data[p_key]:
                formatted_val = "  ".join(prizes_data[p_key]) if "Prize" in p_key and "1st" not in p_key and "2nd" not in p_key and "3rd" not in p_key and "Consolation" not in p_key else "\n".join(prizes_data[p_key])
                msg_output.append(f"{emoji} **{prize_headings.get(p_key, p_key)}**\n`{formatted_val}`\n")

        tts_order = [("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"), ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣")]
        tts_output = []
        for p_key, emoji in tts_order:
            if p_key in prizes_data and prizes_data[p_key]:
                tts_output.append(f"{emoji} {prize_headings.get(p_key, p_key)}")
                for item in prizes_data[p_key]: tts_output.append(to_tts_format(item))
                tts_output.append("")
        
        return "\n".join(msg_output), "\n".join(tts_output), draw_date, prizes_data, prize_headings, clean_lottery_title

    except Exception as e:
        print(f"**[LOG]** Parsing Error: {e}", flush=True)
        return None, None, None, {}, {}, None

# ==========================================
# 2. UTILITIES & BACKGROUND PRE-RENDERER
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

def pre_render_ribbon_bang(title_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH//2, 310
    w, h = 1040, 130
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
    
    font = load_font("extrabold", 44)
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
    w, h = 1040, 120
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
    
    font = load_font("extrabold", 44)
    draw.text((cx, cy-2), title_text.upper(), font=font, fill=(255, 224, 102, 255), anchor="mm") 
    draw.text((cx, cy-5), title_text.upper(), font=font, fill=(58, 5, 0, 255), anchor="mm")
    
    shadow = layer.copy().filter(ImageFilter.GaussianBlur(15))
    shadow_data = np.array(shadow)
    shadow_data[..., :3] = 0
    final = Image.fromarray(shadow_data)
    final.alpha_composite(layer)
    return final

def pre_render_hero_text(text):
    font = load_font("hero", 320)
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH // 2, 570
    bbox = draw.textbbox((cx, cy), text, font=font, anchor="mm")
    text_y_start, text_height = max(0, int(bbox[1])), max(1, int(bbox[3] - bbox[1]))
    
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((cx, cy + 30), text, font=font, fill=(0, 0, 0, 240), anchor="mm")
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(25)))
    
    for i in range(18, 0, -1):
        draw.text((cx, cy + i), text, font=font, fill=(70, 15, 0, 255), anchor="mm")
        
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).text((cx, cy), text, font=font, fill=255, anchor="mm")
    
    stops = [(0.0, (255, 255, 230)), (0.2, (255, 220, 0)), (0.7, (255, 160, 0)), (1.0, (180, 60, 0))]
    grad = generate_vertical_gradient(WIDTH, text_height, stops)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grad_layer.paste(grad, (0, text_y_start))
    layer.paste(grad_layer, (0, 0), mask)
    draw.text((cx, cy), text, font=font, fill=None, outline=(255, 240, 150, 255), stroke_width=4, anchor="mm")
    return layer

def pre_render_glass_card(district_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    bounds = [500, 780, 1420, 1000]
    draw.rounded_rectangle(bounds, radius=30, fill=(20, 10, 35, 230), outline=(255, 215, 0, 190), width=4)
    draw.rounded_rectangle([bounds[0]+2, bounds[1]+2, bounds[2]-2, bounds[3]-2], radius=28, outline=(255, 255, 255, 100), width=2)
    
    f_sub = load_font("bold", 48) 
    f_main = load_font("black", 85) 
    draw.text((WIDTH//2, 835), "WINNING DISTRICT", font=f_sub, fill="#B8C0D0", anchor="mm")
    main_y = 925
    
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    ImageDraw.Draw(glow).text((WIDTH//2, main_y), district_text, font=f_main, fill=(255, 215, 0, 120), anchor="mm")
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(15)))
    
    draw.text((WIDTH//2, main_y + 5), district_text, font=f_main, fill=(0,0,0,230), anchor="mm")
    draw.text((WIDTH//2, main_y), district_text, font=f_main, fill="#FFFFFF", anchor="mm")
    return layer

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
# 3. GLOBAL WORKER VARIABLES
# ==========================================
MP_BG_ASSET = None
MP_RIBBON_ASSET = None
MP_SCROLL_MASK = None
MP_BEAM_TEMPLATE = None
MP_BIG_CARDS_LAYER = None
MP_MATH_CACHE = []
MP_LOTTERY_TITLE = ""

def init_worker_assets(bg_asset, ribbon, scroll_mask, giant_canvas, math_cache, title):
    global MP_BG_ASSET, MP_RIBBON_ASSET, MP_SCROLL_MASK, MP_BEAM_TEMPLATE, MP_BIG_CARDS_LAYER, MP_MATH_CACHE, MP_LOTTERY_TITLE
    MP_BG_ASSET = bg_asset
    MP_RIBBON_ASSET = ribbon
    MP_SCROLL_MASK = scroll_mask
    MP_BIG_CARDS_LAYER = giant_canvas
    MP_MATH_CACHE = math_cache
    MP_LOTTERY_TITLE = title
    
    bt = Image.new("RGBA", (800, HEIGHT), (0,0,0,0))
    ImageDraw.Draw(bt).polygon([(500, 0), (700, 0), (200, HEIGHT), (0, HEIGHT)], fill=(255, 255, 255, 120))
    MP_BEAM_TEMPLATE = bt.filter(ImageFilter.GaussianBlur(15))

def mp_render_single_frame(frame_index):
    m = MP_MATH_CACHE[frame_index]
    canvas = MP_BG_ASSET.copy()
    draw = ImageDraw.Draw(canvas)

    if m['h_op'] > 0.05:
        draw.text((WIDTH//2, m['hy_1']), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, int(255 * m['h_op'])), anchor="mm")
        draw.text((WIDTH//2, m['hy_2']), MP_LOTTERY_TITLE, font=load_font("black", 68), fill=(255, 255, 255, int(255 * m['h_op'])), anchor="mm")

    cards_layer = MP_BIG_CARDS_LAYER.crop((0, m['crop_y'], WIDTH, m['crop_y'] + HEIGHT))
    cards_layer.putalpha(ImageChops.multiply(cards_layer.split()[3], MP_SCROLL_MASK))

    if m['c_op'] < 1.0:
        if m['c_op'] == 0.0:
            cards_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        else:
            cards_layer.putalpha(cards_layer.split()[3].point(lambda p: p * m['c_op']))

    beam_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    beam_layer.paste(MP_BEAM_TEMPLATE, (m['beam_x'] - 350, 0))
    masked_beam = beam_layer.copy()
    masked_beam.putalpha(ImageChops.multiply(beam_layer.split()[3], cards_layer.split()[3]))
    cards_layer.alpha_composite(masked_beam)
    canvas.alpha_composite(cards_layer)

    if m['badge_glitters'] or m['floating_glitters']:
        g_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        g_draw = ImageDraw.Draw(g_layer)
        
        for glitters in [m['badge_glitters'], m['floating_glitters']]:
            for cx, cy, s, op in glitters:
                g_draw.line([(cx-s, cy), (cx+s, cy)], fill=(255, 235, 100, op), width=3)
                g_draw.line([(cx, cy-s), (cx, cy+s)], fill=(255, 235, 100, op), width=3)
                g_draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=(255, 255, 255, op))
                
        canvas.alpha_composite(g_layer.filter(ImageFilter.GaussianBlur(3)))
        canvas.alpha_composite(g_layer)

    if m['r_op'] > 0.01:
        if m['r_op'] < 1.0:
            ribbon_fade = MP_RIBBON_ASSET.copy()
            ribbon_fade.putalpha(ribbon_fade.split()[3].point(lambda p: p * m['r_op']))
            canvas.alpha_composite(ribbon_fade)
        else:
            canvas.alpha_composite(MP_RIBBON_ASSET)

    return cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR)

# ==========================================
# 4. VIDEO RENDERING ENGINES
# ==========================================
def render_bang_video(theme, prize_heading, item, lottery_title, out_path, duration_sec):
    print(f"**[LOG]** Synchronous Bang Render: {out_path}", flush=True)
    bg_asset = pre_render_background(theme)
    total_frames = FPS * duration_sec
    
    ticket_num = item
    district = "KERALA"
    dist_match = re.search(r'\((.*?)\)', item)
    if dist_match:
        district = dist_match.group(1).upper()
        ticket_num = item.replace(dist_match.group(0), "").strip()

    hero_asset = pre_render_hero_text(ticket_num)
    hero_alpha_mask = hero_asset.split()[3]
    ribbon_asset = pre_render_ribbon_bang(prize_heading)
    glass_asset = pre_render_glass_card(district)
    
    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    confetti = []
    confetti_triggered = False
    glass_bounds = [500, 780, 1420, 1000]
    
    box_glitters = [
        {'x': glass_bounds[0], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': glass_bounds[2], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': glass_bounds[0], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.18},
        {'x': glass_bounds[2], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.14},
        {'x': WIDTH//2 - 480, 'y': 310 - 50, 'phase': random.uniform(0, 6), 'speed': 0.10},
        {'x': WIDTH//2 + 480, 'y': 310 - 50, 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': WIDTH//2 - 480, 'y': 310 + 50, 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': WIDTH//2 + 480, 'y': 310 + 50, 'phase': random.uniform(0, 6), 'speed': 0.17},
    ]

    for frame in range(total_frames):
        time_sec = frame / FPS
        canvas = bg_asset.copy()
        draw = ImageDraw.Draw(canvas)

        if time_sec > 0.0:
            op = ease_out_expo(min(time_sec / 0.3, 1.0))
            if op > 0.05:
                draw.text((WIDTH//2, int(90 - (30 * (1 - op)))), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, int(255*op)), anchor="mm")
                draw.text((WIDTH//2, int(165 - (30 * (1 - op)))), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, int(255*op)), anchor="mm")

        if time_sec > 0.2:
            scale = ease_out_back_extreme(min((time_sec - 0.2) / 0.4, 1.0))
            if scale > 0.01:
                w = max(int(WIDTH * scale), 1)
                temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
                temp.paste(ribbon_asset.resize((w, HEIGHT), Image.Resampling.LANCZOS), (int((WIDTH - w) // 2), 0))
                canvas.alpha_composite(temp)

        if time_sec > 0.4:
            slide = ease_out_expo(min((time_sec - 0.4) / 0.3, 1.0))
            temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            temp.paste(glass_asset, (0, int(150 * (1 - slide))))
            canvas.alpha_composite(temp)

        impact_time = 1.0
        shake_dx, shake_dy = 0, 0
        if time_sec > 0.8:
            hp = min((time_sec - 0.8) / 0.2, 1.0)
            scale = 5.0 - (ease_out_expo(hp) * 4.0)
            w_h, h_h = max(int(WIDTH * scale), 1), max(int(HEIGHT * scale), 1)
            temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            temp.paste(hero_asset.resize((w_h, h_h), Image.Resampling.LANCZOS), (int((WIDTH - w_h) // 2), int((HEIGHT - h_h) // 2)))
            canvas.alpha_composite(temp)

            if time_sec >= impact_time:
                if not confetti_triggered:
                    confetti_triggered = True
                    for _ in range(250):
                        angle = random.uniform(0, 2*math.pi)
                        speed = random.uniform(15, 60)
                        confetti.append({'x': WIDTH//2, 'y': 570, 'vx': math.cos(angle)*speed, 'vy': math.sin(angle)*speed-20, 'col': random.choice([(255,215,0), (0,212,255), (255,0,150), (255,255,255)]), 'size': random.randint(4, 15), 'life': 1.0})

                frames_since = int(frame - (impact_time * FPS))
                if frames_since < 5:
                    intensity = int(25 - (frames_since * 5))
                    shake_dx, shake_dy = random.randint(-intensity, intensity), random.randint(-intensity, intensity)

        if time_sec >= impact_time:
            c_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            c_draw = ImageDraw.Draw(c_layer)
            for p in confetti:
                if p['life'] > 0:
                    p['x'] += p['vx']
                    p['y'] += p['vy']
                    p['vy'] += 2.5
                    p['life'] -= 0.02
                    s = int(p['size'])
                    c_draw.rectangle([int(p['x'])-s, int(p['y'])-s//2, int(p['x'])+s, int(p['y'])+s//2], fill=p['col']+(int(255*max(p['life'], 0)),))
            canvas.alpha_composite(c_layer)

            if 1.2 <= time_sec <= 1.8:
                bx = int(200 + (1500 * ((time_sec - 1.2) / 0.6)))
                beam_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
                ImageDraw.Draw(beam_layer).polygon([(bx+100, 0), (bx+300, 0), (bx-100, HEIGHT), (bx-300, HEIGHT)], fill=(255, 255, 255, 200))
                beam_layer = beam_layer.filter(ImageFilter.GaussianBlur(15))
                beam_layer.putalpha(ImageChops.multiply(beam_layer.split()[3], hero_alpha_mask))
                canvas.alpha_composite(beam_layer)

            glitter_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            g_draw = ImageDraw.Draw(glitter_layer)
            for g in box_glitters:
                g['phase'] += g['speed']
                pulse = (math.sin(g['phase']) + 1) / 2
                s = int(5 + 25 * pulse)
                g_op = int(50 + 205 * pulse)
                g_draw.line([(g['x']-s, g['y']), (g['x']+s, g['y'])], fill=(255, 235, 100, g_op), width=3)
                g_draw.line([(g['x'], g['y']-s), (g['x'], g['y']+s)], fill=(255, 235, 100, g_op), width=3)
                g_draw.ellipse([g['x']-4, g['y']-4, g['x']+4, g['y']+4], fill=(255, 255, 255, g_op))
            canvas.alpha_composite(glitter_layer.filter(ImageFilter.GaussianBlur(3)))
            canvas.alpha_composite(glitter_layer)

        final_frame = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,255))
        final_frame.paste(canvas, (int(shake_dx), int(shake_dy)))
        out.write(cv2.cvtColor(np.array(final_frame), cv2.COLOR_RGBA2BGR))
        
        if frame > 0 and frame % 60 == 0:
            print(f"**[LOG]** Rendered Frame {frame}/{total_frames}...", flush=True)

    out.release()
    gc.collect()
    print(f"**[LOG]** FFmpeg Compressing {out_path}...", flush=True)
    subprocess.run(["ffmpeg", "-y", "-i", raw_path, "-vcodec", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)
    return out_path

def render_scroll_video(theme, prize_heading, numbers_list, lottery_title, out_path, duration_sec, is_4col, start_delay, end_delay):
    print(f"**[LOG]** ThreadPool 3-Core Render (Scroll): {out_path} (Start Delay: {start_delay}s, End Delay: {end_delay}s)", flush=True)
    total_frames = FPS * duration_sec
    cols = 4 if is_4col else 2
    
    bg_asset = pre_render_background(theme)
    ribbon_asset = pre_render_ribbon_scroll(prize_heading)

    # 1. GIANT CANVAS
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

    # Scroll Mask
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    m_draw = ImageDraw.Draw(mask)
    fade_start, fade_end = 360, 420
    for y in range(fade_start, fade_end):
        m_draw.line([(0, y), (WIDTH, y)], fill=int(255 * (y - fade_start) / (fade_end - fade_start)))
    m_draw.rectangle([0, fade_end, WIDTH, HEIGHT], fill=255)

    # 2. EXACT MATH CACHE
    print("**[LOG]** Pre-calculating Frame Math...", flush=True)
    math_cache = []
    floating_glitters = []
    
    badge_glitters_state = [
        {'x': WIDTH//2 - 480, 'y': 280 - 50, 'phase': random.uniform(0, 6), 'speed': 0.10},
        {'x': WIDTH//2 + 480, 'y': 280 - 50, 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': WIDTH//2 - 480, 'y': 280 + 50, 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': WIDTH//2 + 480, 'y': 280 + 50, 'phase': random.uniform(0, 6), 'speed': 0.17},
    ]
    
    for frame in range(total_frames):
        time_sec = frame / FPS
        h_op = ease_out_expo(min(max(time_sec / 0.5, 0.0), 1.0)) if time_sec > 0.0 else 0.0
        
        scroll_start = start_delay
        scroll_end = max(scroll_start + 0.5, duration_sec - end_delay)
        
        crop_y = 0
        if scroll_start < time_sec < scroll_end:
            progress = (time_sec - scroll_start) / (scroll_end - scroll_start)
            crop_y = int(max_scroll * ease_in_out_cubic(progress))
        elif time_sec >= scroll_end:
            crop_y = max_scroll
            
        c_op = 1.0
        if time_sec < 0.8:
            c_op = max((time_sec - 0.2) / 0.6, 0.0)
            
        beam_x = int(-400 + (2800 * ((time_sec % 3.0) / 3.0)))
        r_op = ease_out_expo(min(max((time_sec - 0.2) / 0.5, 0.0), 1.0)) if time_sec > 0.2 else 0.0

        if random.random() < 0.5:
            floating_glitters.append({'x': random.randint(150, 1770), 'y': random.randint(350, 1000), 'life': 1.0, 's': random.randint(10, 25)})
        
        f_glitters = []
        for g in floating_glitters:
            if g['life'] > 0:
                g['life'] -= 0.05
                pulse = math.sin(g['life'] * math.pi)
                f_glitters.append((g['x'], g['y'], int(g['s'] * pulse), int(255 * max(pulse, 0))))
        floating_glitters = [g for g in floating_glitters if g['life'] > 0]
        
        b_glitters = []
        if r_op > 0.5:
            for g in badge_glitters_state:
                g['phase'] += g['speed']
                pulse = (math.sin(g['phase']) + 1) / 2
                s = int(5 + 25 * pulse)
                op = int(50 + 205 * pulse)
                b_glitters.append((g['x'], g['y'], s, op))

        math_cache.append({
            'h_op': h_op, 'hy_1': int(60 - (30 * (1 - h_op))), 'hy_2': int(135 - (30 * (1 - h_op))),
            'crop_y': crop_y, 'c_op': c_op, 'beam_x': beam_x, 'r_op': r_op, 
            'floating_glitters': f_glitters, 'badge_glitters': b_glitters
        })

    # 3. TURBO MULTIPROCESSING
    init_worker_assets(bg_asset, ribbon_asset, mask, giant_canvas, math_cache, lottery_title)

    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    workers = min(3, os.cpu_count() or 1)
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for frame_index, bgr_frame in enumerate(executor.map(mp_render_single_frame, range(total_frames), chunksize=15)):
            out.write(bgr_frame)
            if frame_index > 0 and frame_index % 300 == 0:
                elapsed = time.time() - start_time
                fps_speed = frame_index / elapsed if elapsed > 0 else 0
                print(f"**[LOG]** Processed {frame_index}/{total_frames} frames @ {fps_speed:.1f} fps", flush=True)

    out.release()
    
    global MP_BG_ASSET, MP_RIBBON_ASSET, MP_SCROLL_MASK, MP_BEAM_TEMPLATE, MP_BIG_CARDS_LAYER, MP_MATH_CACHE
    MP_BG_ASSET = MP_RIBBON_ASSET = MP_SCROLL_MASK = MP_BEAM_TEMPLATE = MP_BIG_CARDS_LAYER = None
    MP_MATH_CACHE = []
    gc.collect()
    print(f"**[LOG]** FFmpeg Compressing {out_path}...", flush=True)
    subprocess.run(["ffmpeg", "-y", "-i", raw_path, "-vcodec", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)
    return out_path

# ==========================================
# 5. BOT PIPELINE & FFMPEG
# ==========================================
def compress_and_combine(video_files, final_output):
    print(f"**[LOG]** Compressing & Combining {len(video_files)} videos...", flush=True)
    list_path = os.path.join(DOWNLOAD_DIR, "concat_list.txt")
    with open(list_path, "w") as f:
        for vid in video_files:
            f.write(f"file '{vid}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-pix_fmt", "yuv420p", final_output
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.exists(list_path): os.remove(list_path)
    for vid in video_files:
        if os.path.exists(vid): os.remove(vid)

async def execute_result_pipeline(app, chat_id, target_url):
    print(f"**[LOG]** Executing Pipeline for URL: {target_url}", flush=True)
    msg = await app.send_message(chat_id, "🔎 **Fetching lottery draw data...**")
    
    text_msg, tts_txt, draw_date, prizes, prize_headings, lottery_title = parse_lottery_result_page(target_url)
    if not prizes:
        return await msg.edit_text("❌ Scraping failed or no data found. The results may not be fully published yet.")

    # 1. Send Text Chunks
    await msg.delete()
    chunks = [text_msg[i:i+4000] for i in range(0, len(text_msg), 4000)]
    for chunk in chunks:
        await app.send_message(chat_id, chunk)
        await asyncio.sleep(0.5)
        
    # 2. Send TTS Document
    if tts_txt and tts_txt.strip():
        print(f"**[LOG]** Sending TTS Text Document for {draw_date}...", flush=True)
        tts_file = io.BytesIO(tts_txt.encode('utf-8'))
        tts_file.name = f"TTS_{draw_date}.txt"
        await app.send_document(
            chat_id=chat_id,
            document=tts_file,
            caption=f"🗣️ **Malayalam Pronunciation File for TTS**\n📅 `{draw_date}`"
        )
        await asyncio.sleep(0.5)

    # 3. Render Individual Videos Sequentially (Strict Order)
    tier_config = [
        ("1st Prize", "bang", DURATION_1ST_PRIZE, False, "purple", 0, 0),
        ("Consolation Prize", "scroll", DURATION_CONSOLATION, False, "blue", CONSOLATION_START_DELAY, CONSOLATION_END_DELAY),
        ("2nd Prize", "bang", DURATION_2ND_PRIZE, False, "silver", 0, 0),
        ("3rd Prize", "bang", DURATION_3RD_PRIZE, False, "gold", 0, 0),
        ("4th Prize", "scroll", DURATION_4TH_PRIZE, False, "blue", PRIZE_4TH_START_DELAY, PRIZE_4TH_END_DELAY),
        ("5th Prize", "scroll", DURATION_5TH_PRIZE, False, "blue", PRIZE_5TH_START_DELAY, PRIZE_5TH_END_DELAY),
        ("6th Prize", "scroll", DURATION_6TH_PRIZE, False, "blue", PRIZE_6TH_START_DELAY, PRIZE_6TH_END_DELAY),
        ("7th Prize", "scroll", DURATION_7TH_PRIZE, True, "blue", PRIZE_7_8_9_START_DELAY, PRIZE_7_8_9_END_DELAY),
        ("8th Prize", "scroll", DURATION_8TH_PRIZE, True, "blue", PRIZE_7_8_9_START_DELAY, PRIZE_7_8_9_END_DELAY),
        ("9th Prize", "scroll", DURATION_9TH_PRIZE, True, "blue", PRIZE_7_8_9_START_DELAY, PRIZE_7_8_9_END_DELAY),
        ("10th Prize", "scroll", DURATION_10TH_PRIZE, True, "blue", PRIZE_10TH_START_DELAY, PRIZE_10TH_END_DELAY)
    ]

    video_files = []
    
    for p_name, engine, dur, is_4c, theme, start_delay, end_delay in tier_config:
        if p_name in prizes and prizes[p_name]:
            status_msg = await app.send_message(chat_id, f"🎬 **Rendering {p_name} video ({dur}s)...**\n*(Theme: {theme.upper()})*")
            out_path = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}.mp4")
            full_heading = prize_headings.get(p_name, p_name)

            # Strict synchronous call to avoid crashes
            if engine == "bang":
                render_bang_video(theme, full_heading, prizes[p_name][0], lottery_title, out_path, duration_sec=dur)
            else:
                render_scroll_video(theme, full_heading, prizes[p_name], lottery_title, out_path, duration_sec=dur, is_4col=is_4c, start_delay=start_delay, end_delay=end_delay)
            
            video_files.append(out_path)
            await status_msg.edit_text(f"🚀 **Uploading {p_name}...**")
            await app.send_video(chat_id=chat_id, video=out_path, caption=f"🏆 **{p_name}** - `{draw_date}`")
            await status_msg.delete()

    # 4. Combine Final
    if video_files:
        status_msg = await app.send_message(chat_id, "🗜️ **Combining all videos into one final file...**")
        compress_and_combine(video_files, FINAL_OUTPUT_VIDEO)
        
        await status_msg.edit_text("🚀 **Uploading final combined HD video...**")
        await app.send_video(chat_id=chat_id, video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Full Official Draw**\n📅 `{draw_date}`")
        
        await status_msg.delete()
        if os.path.exists(FINAL_OUTPUT_VIDEO): os.remove(FINAL_OUTPUT_VIDEO)
        print("**[LOG]** Process Complete.", flush=True)

# ==========================================
# 6. ASYNC PYROFORK BOT
# ==========================================
async def run_pyrofork_bot():
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
                "👋 **Welcome to Kerala Lottery Video Generator Bot!**\n\n"
                "**Available Commands:**\n"
                "• `/generate` - Fetch today's result & render pipeline\n"
                "• `/gencustom` - Select from last 10 draw dates\n"
                "• `/start` - Show this menu"
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

        @app.on_callback_query(filters.regex(r"^get_(\d{2}-\d{2}-\d{4})"))
        async def handle_get_callback(client, callback_query):
            await callback_query.answer()
            target_date = callback_query.data.replace("get_", "")
            draws = fetch_last_10_draws()
            target_url = next((d['url'] for d in draws if d['date'] == target_date), f"https://www.keralalotteries.net/search?q={target_date}")
            await execute_result_pipeline(app, callback_query.message.chat.id, target_url)

        await app.start()
        print("**[LOG]** Bot Started Successfully.", flush=True)
        await asyncio.Event().wait()
    except Exception as e:
        print(f"**[CRITICAL ERROR]** Bot thread crashed: {e}", flush=True)
    finally:
        if 'app' in locals() and app.is_initialized:
            await app.stop()

# ==========================================
# 7. STREAMLIT THREADING
# ==========================================
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_pyrofork_bot())
        except Exception as e:
            print(f"**[CRITICAL ERROR]** Async loop crashed: {e}", flush=True)
    threading.Thread(target=run_async_loop, daemon=True).start()

start_bot_thread()

st.title("Kerala Lottery Video Engine 🎬")
st.write("Bot is running. Powered by strict synchronous CV2 writing and ThreadPool Executor.")

