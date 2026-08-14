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

# --- CONFIGURATION & PATHS ---
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
    except Exception:
        return []

def parse_lottery_result_page(target_url: str):
    try:
        res = http_get(target_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        post_body = soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse body.", None, None, {}, {}, None

        full_text = post_body.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]

        h1_tag = soup.find('h1', class_='entry-title')
        raw_title = h1_tag.get_text(strip=True) if h1_tag else "KERALA LOTTERY"
        
        clean_match = re.search(r'([A-Za-z\s]+[A-Za-z])\s+([A-Z]{2}-\d{3})', raw_title)
        if clean_match:
            clean_lottery_title = f"{clean_match.group(1).upper()} ({clean_match.group(2)})"
        else:
            clean_lottery_title = re.sub(r'Kerala Lottery Results:|\bOfficial\b|\bResult\b|\bToday\b|\d{2}-\d{2}-\d{4}', '', raw_title, flags=re.IGNORECASE).strip().upper()

        date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', full_text)
        draw_date = date_match.group(1).replace('/', '-') if date_match else "N/A"

        series_match = re.search(r'Today Lottery Series:\s*([A-Z0-9,\s]+)', full_text)
        series_str = series_match.group(1).strip() if series_match else "N/A"

        prize_headers = ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]
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
                    h_clean = re.sub(r'\s+', ' ', line).strip()
                    h_clean = re.sub(r'(' + re.escape(matched_header) + r')\s*(Rs\.)', r'\1 - \2', h_clean, flags=re.IGNORECASE)
                    prize_headings[current_prize_key] = h_clean.upper() 
                continue

            if current_prize_key:
                if (line.startswith("(") and line.endswith(")")) or line in ["...", "---"]: continue
                if current_prize_key in ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line): prizes_data[current_prize_key].append(line)
                else:
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    if four_digits: prizes_data[current_prize_key].extend(four_digits)

        msg_output = [f"🎟️ **{clean_lottery_title}**", f"📅 **Date:** `{draw_date}`", f"🔢 **Series:** `{series_str}`", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        prize_order = [("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"), ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣"), ("7th Prize", "7️⃣"), ("8th Prize", "8️⃣"), ("9th Prize", "9️⃣")]

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
        print(f"[LOG] Parsing Error: {e}")
        return None, None, None, {}, {}, None

# ==========================================
# 2. UTILITIES & BACKGROUND PRE-RENDERER
# ==========================================
def ease_out_expo(x): return 1 if x == 1 else 1 - math.pow(2, -10 * x)
def ease_in_out_cubic(x): return 4 * x**3 if x < 0.5 else 1 - math.pow(-2 * x + 2, 3) / 2
def ease_out_back_extreme(x): return 1 + 3.5 * math.pow(x - 1, 3) + 2.5 * math.pow(x - 1, 2)

def generate_vertical_gradient(w, h, stops):
    grad = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / float(h - 1 if h > 1 else 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i+1][0]:
                range_t = (t - stops[i][0]) / (stops[i+1][0] - stops[i][0])
                c = np.array(stops[i][1]) + (np.array(stops[i+1][1]) - np.array(stops[i][1])) * range_t
                grad[y, :] = [int(c[0]), int(c[1]), int(c[2]), 255]
                break
    return Image.fromarray(grad, mode="RGBA")

def create_and_save_backgrounds():
    print("[LOG] Pre-rendering static backgrounds...")
    themes = {
        "purple": (35, 5, 25, 30, 10, 35),
        "blue": (10, 25, 50, 5, 10, 30),
        "silver": (45, 45, 50, 20, 20, 25),
        "gold": (50, 35, 10, 30, 20, 5)
    }
    y_coords, x_coords = np.ogrid[:HEIGHT, :WIDTH]
    cx, cy = WIDTH / 2, HEIGHT / 2
    norm_dist = np.clip(np.hypot(x_coords - cx, y_coords - cy) / math.hypot(cx, cy), 0, 1)

    bg_paths = {}
    for name, (r1, g1, b1, r2, g2, b2) in themes.items():
        path = os.path.join(DOWNLOAD_DIR, f"bg_{name}.png")
        if not os.path.exists(path):
            r = (r1 + (r2 - r1) * (norm_dist ** 1.8)).astype(np.uint8)
            g = (g1 + (g2 - g1) * (norm_dist ** 1.8)).astype(np.uint8)
            b = (b1 + (b2 - b1) * (norm_dist ** 1.8)).astype(np.uint8)
            canvas = Image.fromarray(np.dstack((r, g, b, np.full((HEIGHT, WIDTH), 255, dtype=np.uint8))), mode="RGBA")
            bl = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            glow_col = (255, 80, 120, 80) if name == "purple" else (80, 150, 255, 80) if name == "blue" else (255, 215, 0, 60)
            ImageDraw.Draw(bl).ellipse([int(cx - 700), int(cy - 200), int(cx + 700), int(cy + 450)], fill=glow_col)
            canvas.alpha_composite(bl.filter(ImageFilter.GaussianBlur(150)))
            canvas.save(path)
        bg_paths[name] = path
    return bg_paths

# ==========================================
# 3. MULTIPROCESSING GLOBALS & RENDERERS
# ==========================================
# These inherit natively to worker processes on Linux (Streamlit Cloud via fork)
MP_BG_ASSET = None
MP_RIBBON_ASSET = None
MP_GIANT_CANVAS = None
MP_MATH_CACHE = []
MP_BEAM_TEMPLATE = None
MP_LOTTERY_TITLE = ""

def init_mp_assets(bg_path, ribbon, giant_canvas, math_cache, title):
    global MP_BG_ASSET, MP_RIBBON_ASSET, MP_GIANT_CANVAS, MP_MATH_CACHE, MP_BEAM_TEMPLATE, MP_LOTTERY_TITLE
    MP_BG_ASSET = Image.open(bg_path).convert("RGBA")
    MP_RIBBON_ASSET = ribbon
    MP_GIANT_CANVAS = giant_canvas
    MP_MATH_CACHE = math_cache
    MP_LOTTERY_TITLE = title
    
    # Pre-render light sweep template
    bt = Image.new("RGBA", (800, HEIGHT), (0,0,0,0))
    ImageDraw.Draw(bt).polygon([(500, 0), (700, 0), (200, HEIGHT), (0, HEIGHT)], fill=(255, 255, 255, 120))
    MP_BEAM_TEMPLATE = bt.filter(ImageFilter.GaussianBlur(15))

def mp_render_single_frame(frame_index):
    m = MP_MATH_CACHE[frame_index]
    canvas = MP_BG_ASSET.copy()
    draw = ImageDraw.Draw(canvas)

    # 1. Header
    if m['h_op'] > 0.05:
        draw.text((WIDTH//2, m['hy_1']), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, int(255*m['h_op'])), anchor="mm")
        draw.text((WIDTH//2, m['hy_2']), MP_LOTTERY_TITLE, font=load_font("black", 68), fill=(255, 255, 255, int(255*m['h_op'])), anchor="mm")

    # 2. Giant Canvas Crop
    visible_cards = MP_GIANT_CANVAS.crop((0, m['scroll_y'], WIDTH, m['scroll_y'] + HEIGHT))

    # 3. Light Sweep Masking
    beam_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    beam_layer.paste(MP_BEAM_TEMPLATE, (m['beam_x'] - 350, 0))
    masked_beam = beam_layer.copy()
    masked_beam.putalpha(ImageChops.multiply(beam_layer.split()[3], visible_cards.split()[3]))
    visible_cards.alpha_composite(masked_beam)
    canvas.alpha_composite(visible_cards)

    # 4. Stars
    for cx, cy, s, op in m['glitters']:
        draw.line([(cx-s, cy), (cx+s, cy)], fill=(255, 255, 255, op), width=2)
        draw.line([(cx, cy-s), (cx, cy+s)], fill=(255, 255, 255, op), width=2)

    # 5. Ribbon
    if m['r_op']:
        canvas.alpha_composite(MP_RIBBON_ASSET)

    return cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR)


def render_bang_video(bg_path, prize_heading, item, lottery_title, out_path, duration_sec):
    print(f"[LOG] OpenCV Single Core Render (Bang): {out_path}")
    bg_asset = Image.open(bg_path).convert("RGBA")
    total_frames = FPS * duration_sec
    
    ticket_num, district = item, "KERALA"
    dist_match = re.search(r'\((.*?)\)', item)
    if dist_match:
        district = dist_match.group(1).upper()
        ticket_num = item.replace(dist_match.group(0), "").strip()

    ribbon_asset = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    r_draw = ImageDraw.Draw(ribbon_asset)
    cx, cy, w, h = WIDTH//2, 310, 1040, 130
    ImageDraw.Draw(Image.new("L", (WIDTH, HEIGHT), 0)).rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], fill=255)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    grad_layer.paste(generate_vertical_gradient(WIDTH, h, [(0.0, (255, 245, 180)), (0.15, (255, 215, 0)), (0.85, (230, 150, 0)), (1.0, (180, 100, 0))]), (0, cy-h//2))
    ribbon_asset.paste(grad_layer, (0,0), Image.new("L", (WIDTH, HEIGHT), 0).rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], fill=255) or None)
    r_draw.rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], outline=(255, 235, 120, 255), width=3)
    r_draw.text((cx, cy-2), prize_heading, font=load_font("extrabold", 44), fill=(255, 224, 102, 255), anchor="mm") 
    r_draw.text((cx, cy-5), prize_heading, font=load_font("extrabold", 44), fill=(58, 5, 0, 255), anchor="mm")

    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))
    
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
                w_rib = max(int(WIDTH * scale), 1)
                temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
                temp.paste(ribbon_asset.resize((w_rib, HEIGHT), Image.Resampling.LANCZOS), (int((WIDTH - w_rib) // 2), 0))
                canvas.alpha_composite(temp)

        if time_sec > 0.8:
            hp = min((time_sec - 0.8) / 0.2, 1.0)
            scale = 5.0 - (ease_out_expo(hp) * 4.0)
            draw.text((WIDTH//2, 570), ticket_num, font=load_font("hero", int(320*scale)), fill=(255, 255, 255, int(255*hp)), stroke_width=4, stroke_fill=(255, 215, 0, int(255*hp)), anchor="mm")
            
        out.write(cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR))

    out.release()
    print(f"[LOG] Compressing {out_path} via FFmpeg...")
    subprocess.run(["ffmpeg", "-y", "-i", raw_path, "-vcodec", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)
    return out_path

def render_scroll_video(bg_path, prize_heading, numbers_list, lottery_title, out_path, duration_sec, is_4col):
    print(f"[LOG] Multiprocessing 3-Core Render (Scroll): {out_path}")
    total_frames = FPS * duration_sec
    cols = 4 if is_4col else 2
    
    # 1. THE GIANT CANVAS TRICK (Drawn once)
    rows = math.ceil(len(numbers_list) / cols)
    total_canvas_h = max(HEIGHT, 440 + (rows * (150 if is_4col else 200)) + 600)
    giant_canvas = Image.new("RGBA", (WIDTH, total_canvas_h), (0,0,0,0))
    g_draw = ImageDraw.Draw(giant_canvas)
    
    for i, num in enumerate(numbers_list):
        col, row = i % cols, i // cols
        c_x = [240, 720, 1200, 1680][col] if is_4col else (540 if col == 0 else 1380)
        c_y = 440 + (row * (150 if is_4col else 200))
        cw, ch = (385, 110) if is_4col else (760, 160)
        g_draw.rounded_rectangle([c_x-cw//2, c_y-ch//2, c_x+cw//2, c_y+ch//2], radius=15, fill=(15, 5, 20, 240), outline=(255, 215, 0, 200), width=3)
        g_draw.text((c_x, c_y), num, font=load_font("hero", 80 if is_4col else 95), fill=(255, 250, 240, 255), anchor="mm")

    # Scroll fade mask
    fade_start, fade_end = 360, 420
    mask = Image.new("L", (WIDTH, total_canvas_h), 255)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rectangle([0, 0, WIDTH, fade_start], fill=0)
    for y in range(fade_start, fade_end): m_draw.line([(0, y), (WIDTH, y)], fill=int(255 * (y - fade_start) / (fade_end - fade_start)))
    giant_canvas.putalpha(ImageChops.multiply(giant_canvas.split()[3], mask))

    # Ribbon
    ribbon_asset = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    r_draw = ImageDraw.Draw(ribbon_asset)
    cx, cy, w, h = WIDTH//2, 280, 1040, 120
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    grad_layer.paste(generate_vertical_gradient(WIDTH, h, [(0.0, (255, 245, 180)), (0.15, (255, 215, 0)), (0.85, (230, 150, 0)), (1.0, (180, 100, 0))]), (0, cy-h//2))
    ribbon_asset.paste(grad_layer, (0,0), Image.new("L", (WIDTH, HEIGHT), 0).rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], fill=255) or None)
    r_draw.rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], outline=(255, 235, 120, 255), width=3)
    r_draw.text((cx, cy-2), prize_heading, font=load_font("extrabold", 44), fill=(255, 224, 102, 255), anchor="mm") 
    r_draw.text((cx, cy-5), prize_heading, font=load_font("extrabold", 44), fill=(58, 5, 0, 255), anchor="mm")

    # 2. MATH CACHE (Pre-compute everything so threads do zero math)[span_4](start_span)[span_4](end_span)
    max_scroll = max(0, rows * (150 if is_4col else 200) - 400)
    math_cache = []
    glitters = []
    
    for frame in range(total_frames):
        time_sec = frame / FPS
        h_op = ease_out_expo(min(time_sec / 0.5, 1.0)) if time_sec > 0.0 else 0.0
        
        scroll_start, scroll_end = 2.0, max(2.5, duration_sec - 2.0)
        scroll_y = 0
        if scroll_start < time_sec < scroll_end:
            scroll_y = int(max_scroll * ease_in_out_cubic((time_sec - scroll_start) / (scroll_end - scroll_start)))
        elif time_sec >= scroll_end:
            scroll_y = max_scroll
            
        if random.random() < 0.5: glitters.append({'x': random.randint(300, 1620), 'y': random.randint(400, 1000), 'life': 1.0, 's': random.randint(8, 20)})
        frame_glitters = []
        for g in glitters:
            if g['life'] > 0:
                g['life'] -= 0.05
                pulse = math.sin(g['life'] * math.pi)
                frame_glitters.append((g['x'], g['y'], int(g['s'] * pulse), int(255 * max(pulse, 0))))
        glitters = [g for g in glitters if g['life'] > 0]
        
        math_cache.append({
            'h_op': h_op, 'hy_1': int(60 - (30 * (1 - h_op))), 'hy_2': int(135 - (30 * (1 - h_op))),
            'scroll_y': scroll_y, 'r_op': time_sec > 0.2, 'beam_x': int(-400 + (2800 * ((time_sec % 2.5) / 2.5))),
            'glitters': frame_glitters
        })

    # Set up globals for worker processes[span_5](start_span)[span_5](end_span)
    init_mp_assets(bg_path, ribbon_asset, giant_canvas, math_cache, lottery_title)

    # 3. TURBO MULTIPROCESSING RENDER[span_6](start_span)[span_6](end_span)
    raw_path = out_path.replace(".mp4", "_raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(raw_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    workers = min(3, os.cpu_count() or 1)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for bgr_frame in executor.map(mp_render_single_frame, range(total_frames), chunksize=15):
            out.write(bgr_frame)
            
    out.release()
    
    print(f"[LOG] Compressing {out_path} via FFmpeg...")
    subprocess.run(["ffmpeg", "-y", "-i", raw_path, "-vcodec", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_path): os.remove(raw_path)
    return out_path

# ==========================================
# 4. BOT PIPELINE (Sequential with New Messages)
# ==========================================
async def execute_result_pipeline(app, chat_id, target_url):
    print(f"[LOG] Executing Pipeline for URL: {target_url}")
    await app.send_message(chat_id, "🔎 **Fetching lottery draw data...**")
    
    text_msg, tts_txt, draw_date, prizes, prize_headings, lottery_title = parse_lottery_result_page(target_url)
    if not prizes:
        return await app.send_message(chat_id, "❌ Scraping failed or no data found.")

    # 1. Send Text
    chunks = [text_msg[i:i+4000] for i in range(0, len(text_msg), 4000)]
    for chunk in chunks:
        await app.send_message(chat_id, chunk)
        await asyncio.sleep(0.5)
        
    # 2. Send TTS Document
    if tts_txt and tts_txt.strip():
        print(f"[LOG] Sending TTS Text Document for {draw_date}...")
        tts_file = io.BytesIO(tts_txt.encode('utf-8'))
        tts_file.name = f"TTS_{draw_date}.txt"
        await app.send_document(
            chat_id=chat_id,
            document=tts_file,
            caption=f"🗣️ **Malayalam Pronunciation File for TTS**\n📅 `{draw_date}`"
        )
        await asyncio.sleep(0.5)

    # 3. Render Backgrounds
    bg_msg = await app.send_message(chat_id, "⚙️ **Pre-rendering graphical background themes...**")
    bg_paths = await asyncio.to_thread(create_and_save_backgrounds)
    await bg_msg.delete()

    # 4. Sequentially Render & Upload Individual Videos
    tier_config = [
        ("1st Prize", "bang", 10, False, "purple"),
        ("2nd Prize", "bang", 10, False, "silver"),
        ("3rd Prize", "bang", 10, False, "gold"),
        ("Consolation Prize", "scroll", 10, False, "blue"),
        ("4th Prize", "scroll", 25, False, "blue"),
        ("5th Prize", "scroll", 25, False, "blue"),
        ("6th Prize", "scroll", 25, False, "blue"),
        ("7th Prize", "scroll", 90, True, "blue"),
        ("8th Prize", "scroll", 90, True, "blue"),
        ("9th Prize", "scroll", 90, True, "blue")
    ]

    video_files = []
    
    for p_name, engine, dur, is_4c, theme in tier_config:
        if p_name in prizes and prizes[p_name]:
            status_msg = await app.send_message(chat_id, f"🎬 **Rendering {p_name} video ({dur}s)...**\n*(Theme: {theme.upper()})*")
            out_path = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}.mp4")
            full_heading = prize_headings.get(p_name, p_name)

            if engine == "bang":
                await asyncio.to_thread(render_bang_video, bg_paths[theme], full_heading, prizes[p_name][0], lottery_title, out_path, dur)
            else:
                await asyncio.to_thread(render_scroll_video, bg_paths[theme], full_heading, prizes[p_name], lottery_title, out_path, dur, is_4c)
            
            video_files.append(out_path)
            await status_msg.edit_text(f"🚀 **Uploading {p_name}...**")
            await app.send_video(chat_id=chat_id, video=out_path, caption=f"🏆 **{p_name}** - `{draw_date}`")
            await status_msg.delete()

    # 5. Combine Final
    status_msg = await app.send_message(chat_id, "🗜️ **Combining all videos into one final file...**")
    list_path = os.path.join(DOWNLOAD_DIR, "concat.txt")
    with open(list_path, "w") as f:
        for vid in video_files: f.write(f"file '{vid}'\n")
    
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c:v", "copy", FINAL_OUTPUT_VIDEO], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    await status_msg.edit_text("🚀 **Uploading final combined HD video...**")
    await app.send_video(chat_id=chat_id, video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Full Official Draw**\n📅 `{draw_date}`")
    
    await status_msg.delete()
    for f in video_files + [FINAL_OUTPUT_VIDEO, list_path]: 
        if os.path.exists(f): os.remove(f)
    print("[LOG] Process Complete.")

# ==========================================
# 5. ASYNC PYROFORK BOT
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
        print("[LOG] Bot Started Successfully.")
        await asyncio.Event().wait()
    except Exception as e:
        print(f"[CRITICAL ERROR] Bot thread crashed: {e}")
    finally:
        if 'app' in locals() and app.is_initialized:
            await app.stop()

# ==========================================
# 6. STREAMLIT THREADING
# ==========================================
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_pyrofork_bot())
        except Exception as e:
            print(f"[CRITICAL ERROR] Async loop crashed: {e}")
    threading.Thread(target=run_async_loop, daemon=True).start()

start_bot_thread()

st.title("Kerala Lottery Video Engine 🎬")
st.write("Bot is running. Powered by 3-Core Multiprocessing & Fast OpenCV writing for Maximum Output Speed.")

