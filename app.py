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
from datetime import datetime
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# --- CONFIGURATION & PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "renders")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FINAL_OUTPUT_VIDEO = os.path.join(DOWNLOAD_DIR, "final_combined_lottery.mp4")

FPS = 30
WIDTH, HEIGHT = 1920, 1080

# --- FONT LOADER (Looks in repository root first) ---
FONTS = {
    "hero": os.path.join(BASE_DIR, "Anton-Regular.ttf"),
    "black": os.path.join(BASE_DIR, "Montserrat-Black.ttf"),
    "extrabold": os.path.join(BASE_DIR, "Montserrat-ExtraBold.ttf"),
    "bold": os.path.join(BASE_DIR, "Montserrat-Bold.ttf"),
    "medium": os.path.join(BASE_DIR, "Montserrat-Medium.ttf")
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
    """Converts ticket numbers to comma-separated Malayalam words for TTS."""
    match_series = re.match(r'^([A-Z]{2})\s*(\d{6})(.*)$', ticket_str)
    if match_series:
        series, number, extra = match_series.group(1), match_series.group(2), match_series.group(3).strip()
        s_parts = [ALPHA_TO_ML.get(c, c) for c in series]
        n_parts = [DIGITS_TO_ML.get(d, d) for d in number]
        combined = " , ".join(s_parts + n_parts)
        if extra:
            combined += f" {extra}"
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
            return "❌ Could not parse lottery result page body.", None, None, {}

        full_text = post_body.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]

        h1_tag = soup.find('h1', class_='entry-title')
        raw_title = h1_tag.get_text(strip=True) if h1_tag else "Kerala Lottery Result"
        clean_title = re.sub(r'Kerala Lottery Results:|\bOfficial\b|\bResult\b|\bToday\b', '', raw_title, flags=re.IGNORECASE).strip()

        date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', full_text)
        draw_date = date_match.group(1).replace('/', '-') if date_match else "N/A"

        series_match = re.search(r'Today Lottery Series:\s*([A-Z0-9,\s]+)', full_text)
        series_str = series_match.group(1).strip() if series_match else "N/A"

        prize_headers = [
            "1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize",
            "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"
        ]

        hard_stop_phrases = ["prize winners are advised to verify", "government gazette", "tomorrow draw details"]

        prizes_data = {}
        prize_headings = {}
        current_prize_key = None

        for line in lines:
            line_lower = line.lower()
            if any(sp in line_lower for sp in hard_stop_phrases): break

            matched_header = next((ph for ph in prize_headers if ph.lower() in line_lower), None)
            if matched_header:
                current_prize_key = matched_header
                if current_prize_key not in prizes_data:
                    prizes_data[current_prize_key] = []
                    heading_clean = re.sub(r'\s+', ' ', line).strip()
                    heading_clean = re.sub(r'(' + re.escape(matched_header) + r')\s*(Rs\.)', r'\1 - \2', heading_clean, flags=re.IGNORECASE)
                    prize_headings[current_prize_key] = heading_clean
                continue

            if current_prize_key:
                if (line.startswith("(") and line.endswith(")")) or line in ["...", "---"]: continue
                if current_prize_key in ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line):
                        prizes_data[current_prize_key].append(line)
                else:
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    if four_digits: prizes_data[current_prize_key].extend(four_digits)

        # 1. TELEGRAM TEXT MESSAGE
        msg_output = [
            f"🎟️ **{clean_title}**",
            f"📅 **Date:** `{draw_date}`",
            f"🔢 **Series:** `{series_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        prize_order = [
            ("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"),
            ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"),
            ("6th Prize", "6️⃣"), ("7th Prize", "7️⃣"), ("8th Prize", "8️⃣"), ("9th Prize", "9️⃣")
        ]

        for p_key, emoji in prize_order:
            if p_key in prizes_data and prizes_data[p_key]:
                heading_text = prize_headings.get(p_key, p_key)
                vals = prizes_data[p_key]
                formatted_val = "  ".join(vals) if p_key in ["4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"] else "\n".join(vals)
                msg_output.append(f"{emoji} **{heading_text}**\n`{formatted_val}`\n")

        # 2. TTS TXT FILE
        tts_order = [
            ("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"),
            ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣")
        ]
        tts_output = []
        for p_key, emoji in tts_order:
            if p_key in prizes_data and prizes_data[p_key]:
                tts_output.append(f"{emoji} {prize_headings.get(p_key, p_key)}")
                for item in prizes_data[p_key]:
                    tts_output.append(to_tts_format(item))
                tts_output.append("")

        return "\n".join(msg_output), "\n".join(tts_output), draw_date, prizes_data

    except Exception as e:
        return f"❌ Error parsing results: {str(e)}", None, None, {}
    finally:
        gc.collect()

# ==========================================
# 2. ANIMATION UTILITIES & ASSETS
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

def pre_render_background():
    y_coords, x_coords = np.ogrid[:HEIGHT, :WIDTH]
    cx, cy = WIDTH / 2, HEIGHT / 2
    norm_dist = np.clip(np.hypot(x_coords - cx, y_coords - cy) / math.hypot(cx, cy), 0, 1)
    
    r = (35 + (5 - 35) * (norm_dist ** 1.8)).astype(np.uint8)
    g = (5 + (0 - 5) * (norm_dist ** 1.8)).astype(np.uint8)
    b = (25 + (10 - 25) * (norm_dist ** 1.8)).astype(np.uint8)
    canvas = Image.fromarray(np.dstack((r, g, b, np.full((HEIGHT, WIDTH), 255, dtype=np.uint8))), mode="RGBA")
    
    bl = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(bl).ellipse([int(cx - 700), int(cy - 200), int(cx + 700), int(cy + 450)], fill=(255, 80, 120, 80))
    canvas.alpha_composite(bl.filter(ImageFilter.GaussianBlur(150)))
    return canvas

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

def pre_render_ribbon(title_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    cx, cy, w, h = WIDTH//2, 310, 1040, 130
    x1, y1, x2, y2 = cx - w//2, cy - h//2, cx + w//2, cy + h//2
    
    mask_c = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask_c).rectangle([x1, y1, x2, y2], fill=255)
    stops = [(0.0, (255, 245, 180)), (0.15, (255, 215, 0)), (0.85, (230, 150, 0)), (1.0, (180, 100, 0))]
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    grad_layer.paste(generate_vertical_gradient(WIDTH, h, stops), (0, y1))
    layer.paste(grad_layer, (0,0), mask_c)
    draw.rectangle([x1, y1, x2, y2], outline=(255, 235, 120, 255), width=3)
    
    font = load_font("extrabold", 44)
    draw.text((cx, cy-2), title_text.upper(), font=font, fill=(255, 224, 102, 255), anchor="mm") 
    draw.text((cx, cy-5), title_text.upper(), font=font, fill=(58, 5, 0, 255), anchor="mm")
    
    shadow_data = np.array(layer.copy().filter(ImageFilter.GaussianBlur(15)))
    shadow_data[..., :3] = 0
    final = Image.fromarray(shadow_data)
    final.alpha_composite(layer)
    return final

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

def pre_render_scroll_mask():
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(mask)
    fade_start, fade_end = 360, 420
    for y in range(fade_start, fade_end):
        draw.line([(0, y), (WIDTH, y)], fill=int(255 * (y - fade_start) / (fade_end - fade_start)))
    draw.rectangle([0, fade_end, WIDTH, HEIGHT], fill=255)
    return mask

# ==========================================
# 3. VIDEO RENDER ENGINES
# ==========================================
def render_bang_video(prize_name, item, lottery_title, out_path, duration_sec=10):
    """Engine 1: Poothiri Bang Animation (For 1st, 2nd, 3rd)"""
    total_frames = FPS * duration_sec
    bg_asset = pre_render_background()
    
    # Parse Ticket Number and District
    ticket_num = item
    district = "KERALA"
    dist_match = re.search(r'\((.*?)\)', item)
    if dist_match:
        district = dist_match.group(1).upper()
        ticket_num = item.replace(dist_match.group(0), "").strip()

    hero_asset = pre_render_hero_text(ticket_num)
    hero_alpha_mask = hero_asset.split()[3]
    ribbon_asset = pre_render_ribbon(prize_name)
    glass_asset = pre_render_glass_card(district)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    confetti = []
    confetti_triggered = False
    glass_bounds = [500, 780, 1420, 1000]
    box_glitters = [
        {'x': glass_bounds[0], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.15},
        {'x': glass_bounds[2], 'y': glass_bounds[1], 'phase': random.uniform(0, 6), 'speed': 0.12},
        {'x': glass_bounds[0], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.18},
        {'x': glass_bounds[2], 'y': glass_bounds[3], 'phase': random.uniform(0, 6), 'speed': 0.14},
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
            w, h = max(int(WIDTH * scale), 1), max(int(HEIGHT * scale), 1)
            temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
            temp.paste(hero_asset.resize((w, h), Image.Resampling.LANCZOS), (int((WIDTH - w) // 2), int((HEIGHT - h) // 2)))
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
            canvas.alpha_composite(glitter_layer.filter(ImageFilter.GaussianBlur(3)))

        final_frame = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,255))
        final_frame.paste(canvas, (int(shake_dx), int(shake_dy)))
        out.write(cv2.cvtColor(np.array(final_frame), cv2.COLOR_RGBA2BGR))

    out.release()
    gc.collect()

def render_scroll_video(prize_name, numbers_list, lottery_title, out_path, duration_sec=25, is_4col=False):
    """Engine 2 & 3: Smooth PDF-Style Scrolling (For Consolation and 4th to 9th)"""
    total_frames = FPS * duration_sec
    bg_asset = pre_render_background()
    ribbon_asset = pre_render_ribbon(prize_name)
    scroll_mask = pre_render_scroll_mask()
    
    cols = 4 if is_4col else 2
    cards = [pre_render_grid_card(num, is_small=is_4col) for num in numbers_list]
    
    rows = math.ceil(len(numbers_list) / cols)
    max_scroll = max(0, rows * (150 if is_4col else 200) - 400)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, FPS, (WIDTH, HEIGHT))
    glitters = []

    for frame in range(total_frames):
        time_sec = frame / FPS
        canvas = bg_asset.copy()
        draw = ImageDraw.Draw(canvas)

        if time_sec > 0.0:
            op = ease_out_expo(min(time_sec / 0.5, 1.0))
            if op > 0.05:
                draw.text((WIDTH//2, int(60 - (30 * (1 - op)))), "KERALA STATE LOTTERIES • OFFICIAL RESULT", font=load_font("bold", 26), fill=(200, 208, 224, int(255*op)), anchor="mm")
                draw.text((WIDTH//2, int(135 - (30 * (1 - op)))), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, int(255*op)), anchor="mm")

        scroll_y_offset = 0
        scroll_start, scroll_end = 2.0, max(2.5, duration_sec - 2.0)
        if scroll_start < time_sec < scroll_end:
            prog = (time_sec - scroll_start) / (scroll_end - scroll_start)
            scroll_y_offset = -int(max_scroll * ease_in_out_cubic(prog))
        elif time_sec >= scroll_end:
            scroll_y_offset = -max_scroll

        cards_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        for i, card in enumerate(cards):
            col = i % cols
            row = i // cols
            cx = [240, 720, 1200, 1680][col] if is_4col else (540 if col == 0 else 1380)
            base_cy = 440 + (row * (150 if is_4col else 200))
            curr_cy = base_cy + scroll_y_offset

            if 100 < curr_cy < HEIGHT + 200:
                cw, ch = card.size
                cards_layer.paste(card, (int(cx - cw//2), int(curr_cy - ch//2)), card)

        cards_layer.putalpha(ImageChops.multiply(cards_layer.split()[3], scroll_mask))

        # Light sweep
        sweep_prog = (time_sec % 2.5) / 2.5
        bx = int(-400 + (2800 * sweep_prog))
        beam_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        ImageDraw.Draw(beam_layer).polygon([(bx+150, 0), (bx+350, 0), (bx-150, HEIGHT), (bx-350, HEIGHT)], fill=(255, 255, 255, 120))
        beam_layer = beam_layer.filter(ImageFilter.GaussianBlur(15))
        beam_layer.putalpha(ImageChops.multiply(beam_layer.split()[3], cards_layer.split()[3]))
        
        cards_layer.alpha_composite(beam_layer)
        canvas.alpha_composite(cards_layer)

        if random.random() < 0.5:
            glitters.append({'x': random.randint(300, 1620), 'y': random.randint(400, 1000), 'life': 1.0, 's': random.randint(10, 25)})

        g_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
        g_draw = ImageDraw.Draw(g_layer)
        for g in glitters:
            if g['life'] > 0:
                g['life'] -= 0.05
                pulse = math.sin(g['life'] * math.pi)
                op, s = int(255 * max(pulse, 0)), int(g['s'] * pulse)
                cx, cy = int(g['x']), int(g['y'])
                g_draw.line([(cx-s, cy), (cx+s, cy)], fill=(255, 255, 255, op), width=2)
                g_draw.line([(cx, cy-s), (cx, cy+s)], fill=(255, 255, 255, op), width=2)
        canvas.alpha_composite(g_layer)

        if time_sec > 0.2:
            rp = min((time_sec - 0.2) / 0.5, 1.0)
            canvas.alpha_composite(ribbon_asset)

        out.write(cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR))

    out.release()
    gc.collect()

# ==========================================
# 4. FFMPEG COMPRESSION ENGINE
# ==========================================
def compress_and_combine(video_files, final_output):
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

# ==========================================
# 5. ASYNC PYROFORK BOT
# ==========================================
async def execute_result_pipeline(app, chat_id, message, target_url):
    msg = await message.reply_text("🔎 **Fetching lottery draw data...**")
    
    text_msg, tts_txt, draw_date, prizes = parse_lottery_result_page(target_url)
    if not prizes:
        return await msg.edit_text(text_msg)

    # 1. Send Main Telegram Text Message
    chunks = [text_msg[i:i+4000] for i in range(0, len(text_msg), 4000)]
    for chunk in chunks:
        await app.send_message(chat_id, chunk)
        await asyncio.sleep(1.0)

    # 2. Send TTS Malayalam Text File
    if tts_txt and tts_txt.strip():
        tts_file = io.BytesIO(tts_txt.encode('utf-8'))
        tts_file.name = f"TTS_{draw_date}.txt"
        await app.send_document(
            chat_id=chat_id,
            document=tts_file,
            caption=f"🗣️ **Malayalam Pronunciation File for TTS**\n📅 `{draw_date}`"
        )

    # Extract Title from Header Text
    lottery_title = text_msg.split('\n')[0].replace("🎟️", "").strip()

    # 3. Video Pipeline
    video_files = []
    
    # Tier 1: First, Consolation, Second, Third
    tier_config = [
        ("1st Prize", "bang", 10, False),
        ("Consolation Prize", "scroll", 10, False),
        ("2nd Prize", "bang", 10, False),
        ("3rd Prize", "bang", 10, False),
        ("4th Prize", "scroll", 25, False),
        ("5th Prize", "scroll", 25, False),
        ("6th Prize", "scroll", 25, False),
        ("7th Prize", "scroll", 90, True),
        ("8th Prize", "scroll", 90, True),
        ("9th Prize", "scroll", 90, True)
    ]

    for p_name, engine_type, dur, is_4c in tier_config:
        if p_name in prizes and prizes[p_name]:
            await msg.edit_text(f"🎬 **Rendering {p_name} video ({dur}s)...**")
            await asyncio.sleep(0.5)

            out_path = os.path.join(DOWNLOAD_DIR, f"{p_name.replace(' ', '_')}.mp4")
            
            if engine_type == "bang":
                render_bang_video(p_name, prizes[p_name][0], lottery_title, out_path, duration_sec=dur)
            else:
                render_scroll_video(p_name, prizes[p_name], lottery_title, out_path, duration_sec=dur, is_4col=is_4c)

            video_files.append(out_path)
            
            await msg.edit_text(f"🚀 **Uploading {p_name} video...**")
            await app.send_video(chat_id=chat_id, video=out_path, caption=f"🏆 **{p_name}** - `{draw_date}`")

    # 4. FFmpeg Compression & Final Output
    await msg.edit_text("🗜️ **Combining and compressing all prize videos into a single file...**")
    await asyncio.sleep(0.5)
    
    compress_and_combine(video_files, FINAL_OUTPUT_VIDEO)

    await msg.edit_text("🚀 **Uploading final combined HD lottery video...**")
    await app.send_video(chat_id=chat_id, video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title} - Full Official Draw Render**\n📅 `{draw_date}`")
    
    await msg.delete()
    if os.path.exists(FINAL_OUTPUT_VIDEO): os.remove(FINAL_OUTPUT_VIDEO)
    gc.collect()


async def run_pyrofork_bot():
    app = Client("lottery_bot", api_id=st.secrets["API_ID"], api_hash=st.secrets["API_HASH"], bot_token=st.secrets["BOT_TOKEN"])

    @app.on_message(filters.command("start") & filters.private)
    async def handle_start(client, message):
        welcome = (
            "👋 **Welcome to Kerala Lottery Results & Video Generator Bot!**\n\n"
            "**Available Commands:**\n"
            "• `/generate` - Fetch today's result, TTS file & render videos\n"
            "• `/gencustom` - Select from last 10 draw dates\n"
            "• `/start` - Show this menu"
        )
        await message.reply_text(welcome)

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        draws = fetch_last_10_draws()
        if not draws:
            return await message.reply_text("❌ Could not retrieve draw list.")
        await execute_result_pipeline(app, message.chat.id, message, draws[0]['url'])

    @app.on_message(filters.command("gencustom") & filters.private)
    async def handle_gencustom(client, message):
        msg = await message.reply_text("⏳ **Fetching last 10 draw dates...**")
        draws = fetch_last_10_draws()
        if not draws:
            return await msg.edit_text("❌ Failed to fetch draw history.")

        text_lines = ["📅 **Select a date to view and generate lottery video:**\n"]
        keyboard_buttons = []

        for item in draws:
            d_str = item['date']
            cmd_date = d_str.replace('-', '_')
            title = item['title']
            text_lines.append(f"• **{d_str}** - {title}\n  👉 `/get_{cmd_date}`\n")
            keyboard_buttons.append([InlineKeyboardButton(f"📅 {d_str} | {title[:20]}...", callback_data=f"get_{cmd_date}")])

        await message.reply_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(keyboard_buttons))
        await msg.delete()

    @app.on_message(filters.regex(r"^/get_(\d{2}_\d{2}_\d{4})") & filters.private)
    async def handle_get_command(client, message):
        date_key = message.text.strip().replace("/get_", "")
        target_date = date_key.replace('_', '-')
        draws = fetch_last_10_draws()
        target_url = next((d['url'] for d in draws if d['date'] == target_date), f"https://www.keralalotteries.net/search?q={target_date}")
        await execute_result_pipeline(app, message.chat.id, message, target_url)

    @app.on_callback_query(filters.regex(r"^get_(\d{2}_\d{2}_\d{4})"))
    async def handle_get_callback(client, callback_query):
        await callback_query.answer()
        date_key = callback_query.data.replace("get_", "")
        target_date = date_key.replace('_', '-')
        draws = fetch_last_10_draws()
        target_url = next((d['url'] for d in draws if d['date'] == target_date), f"https://www.keralalotteries.net/search?q={target_date}")
        await execute_result_pipeline(app, callback_query.message.chat.id, callback_query.message, target_url)

    await app.start()
    try: await asyncio.Event().wait()
    finally: await app.stop()

# ==========================================
# 6. STREAMLIT THREADING
# ==========================================
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_pyrofork_bot())
    threading.Thread(target=run_async_loop, daemon=True).start()

start_bot_thread()

st.title("Kerala Lottery Bot 🍀")
st.write("Pyrofork Bot Active. Uses `/generate` or `/gencustom` to deliver Text, TTS File, Individual Videos, and FFmpeg Compressed Combined Render.")

