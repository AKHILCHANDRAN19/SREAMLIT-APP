import streamlit as st
import asyncio
import threading
import re
import gc
import os
import math
import random
import time
import numpy as np
import cv2
import subprocess
import concurrent.futures
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# --- CONFIGURATION ---
DOWNLOAD_DIR = "/tmp" if os.name == 'posix' else os.path.join(os.path.expanduser("~"), "Downloads")
FINAL_OUTPUT_VIDEO = os.path.join(DOWNLOAD_DIR, "final_lottery_result.mp4")

FPS = 30
WIDTH, HEIGHT = 1920, 1080

# Fallback to default if custom fonts aren't found on the cloud server
def load_font(font_key, size):
    try:
        font_paths = {
            "hero": "Anton-Regular.ttf", "black": "Montserrat-Black.ttf",
            "extrabold": "Montserrat-ExtraBold.ttf", "bold": "Montserrat-Bold.ttf"
        }
        return ImageFont.truetype(os.path.join(DOWNLOAD_DIR, font_paths.get(font_key, "")), size)
    except:
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

# ==========================================
# 1. SCRAPING LOGIC
# ==========================================
def fetch_today_lottery():
    base_url = "https://www.keralalotteries.net/?m=1"
    try:
        res = http_get(base_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        target_link, lottery_title = None, None
        for row in soup.find_all('tr'):
            links = row.find_all('a', href=True)
            for a in links:
                if re.search(r'/\d{4}/\d{2}/.*kerala-lottery-result.*\.html', a['href']):
                    target_link = a['href']
                    lottery_title = a.get_text(strip=True).replace(" Official Result", "")
                    break
            if target_link: break
            
        if not target_link: return None, "Link not found."

        page_res = http_get(target_link)
        page_soup = BeautifulSoup(page_res.text, 'html.parser')
        post_body = page_soup.find('div', id=re.compile(r'post-body-'))
        
        lines = [line.strip() for line in post_body.get_text(separator='\n', strip=True).split('\n') if line.strip()]
        
        prizes = {}
        current_prize = None
        headers = ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize", 
                   "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]

        for line in lines:
            if "verify the winning numbers" in line.lower(): break
            
            matched = next((h for h in headers if h.lower() in line.lower()), None)
            if matched:
                current_prize = matched
                prizes[current_prize] = []
                continue

            if current_prize:
                if line.startswith("(") or line == "..." or line == "---": continue
                
                if current_prize in ["1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line):
                        prizes[current_prize].append(line)
                else:
                    digits = re.findall(r'\b\d{4}\b', line)
                    if digits: prizes[current_prize].extend(digits)

        return prizes, lottery_title
    except Exception as e:
        return None, str(e)

# ==========================================
# 2. SHARED VIDEO ASSET GENERATORS
# ==========================================
def ease_out_expo(x): return 1 if x == 1 else 1 - math.pow(2, -10 * x)
def ease_in_out_cubic(x): return 4 * x**3 if x < 0.5 else 1 - math.pow(-2 * x + 2, 3) / 2

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
    
    r = (30 + (5 - 30) * (norm_dist ** 1.8)).astype(np.uint8)
    g = (10 + (0 - 10) * (norm_dist ** 1.8)).astype(np.uint8)
    b = (35 + (15 - 35) * (norm_dist ** 1.8)).astype(np.uint8)
    a = np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)
    canvas = Image.fromarray(np.dstack((r, g, b, a)), mode="RGBA")
    
    bl = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(bl).ellipse([int(cx - 700), int(cy - 200), int(cx + 700), int(cy + 450)], fill=(120, 50, 150, 60))
    canvas.alpha_composite(bl.filter(ImageFilter.GaussianBlur(150)))
    return canvas

def pre_render_ribbon(title_text):
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    draw = ImageDraw.Draw(layer)
    cx, cy, w, h = WIDTH//2, 280, 1040, 120
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

# ==========================================
# 3. VIDEO RENDERERS
# ==========================================
def render_bang_video(prize_name, item, lottery_title, out_path):
    """Engine 1: Explosive Bang Animation (For 1st, 2nd, 3rd)"""
    duration = 6
    bg = pre_render_background()
    ribbon = pre_render_ribbon(f"{prize_name}")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    for frame in range(FPS * duration):
        time_sec = frame / FPS
        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)
        
        # Header
        if time_sec > 0.0:
            op = ease_out_expo(min(time_sec / 0.3, 1.0))
            if op > 0.05:
                draw.text((WIDTH//2, int(90 - (30 * (1 - op)))), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, int(255*op)), anchor="mm")
        
        # Ribbon
        if time_sec > 0.2:
            scale = min(max((time_sec - 0.2) / 0.4, 0.0), 1.0)
            if scale > 0.01:
                w = max(int(WIDTH * scale), 1)
                temp = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
                temp.paste(ribbon.resize((w, HEIGHT), Image.Resampling.LANCZOS), (int((WIDTH - w) // 2), 0))
                canvas.alpha_composite(temp)

        # Main Ticket Text
        if time_sec > 0.8:
            hp = min(max((time_sec - 0.8) / 0.2, 0.0), 1.0) 
            scale = 5.0 - (ease_out_expo(hp) * 4.0)
            draw.text((WIDTH//2, HEIGHT//2), item, font=load_font("hero", int(150*scale)), fill=(255,215,0, int(255*hp)), anchor="mm")

        bgr_frame = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR)
        out.write(bgr_frame)
    out.release()
    gc.collect()

def render_scroll_video(prize_name, numbers_list, lottery_title, out_path, is_long=False):
    """Engine 2 & 3: Smooth PDF-Style Scrolling (For 4th - 9th)"""
    duration = 90 if is_long else 16
    bg = pre_render_background()
    ribbon = pre_render_ribbon(f"{prize_name}")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, FPS, (WIDTH, HEIGHT))
    
    cols = 4 if is_long else 2
    max_scroll = (len(numbers_list) // cols) * 150
    
    for frame in range(FPS * duration):
        time_sec = frame / FPS
        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)
        
        if time_sec > 0.0:
            op = ease_out_expo(min(time_sec / 0.5, 1.0))
            draw.text((WIDTH//2, int(60 - (30 * (1 - op)))), lottery_title, font=load_font("black", 68), fill=(255, 255, 255, int(255*op)), anchor="mm")

        scroll_y = 0
        if 2.0 < time_sec < (duration - 2.0):
            prog = (time_sec - 2.0) / (duration - 4.0)
            scroll_y = -int(max_scroll * ease_in_out_cubic(prog))
        elif time_sec >= (duration - 2.0):
            scroll_y = -max_scroll

        for i, num in enumerate(numbers_list):
            row = i // cols
            col = i % cols
            cx = (WIDTH // (cols+1)) * (col + 1)
            cy = 440 + (row * 150) + scroll_y
            
            if 350 < cy < HEIGHT + 100:
                draw.text((cx, cy), num, font=load_font("hero", 60), fill="white", anchor="mm")

        canvas.alpha_composite(ribbon)
        out.write(cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGR))
        
    out.release()
    gc.collect()

# ==========================================
# 4. FFMPEG COMPRESSION & CONCATENATION
# ==========================================
def compress_and_combine(video_files, final_output):
    """Lossless FFmpeg compression using libx264."""
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
    
    os.remove(list_path)
    for vid in video_files: 
        if os.path.exists(vid):
            os.remove(vid)

# ==========================================
# 5. ASYNC PYROFORK BOT
# ==========================================
async def run_pyrofork_bot():
    app = Client("lottery_bot", api_id=st.secrets["API_ID"], api_hash=st.secrets["API_HASH"], bot_token=st.secrets["BOT_TOKEN"])

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("⏳ **Scraping data and initiating Video Rendering Pipeline...**")
        
        prizes, lottery_title = fetch_today_lottery()
        if not prizes:
            return await msg.edit_text(f"❌ Scraping Failed: {lottery_title}")

        video_files = []
        
        # 1. First, Second, Third Prizes (Bang Animation)
        for p in ["1st Prize", "2nd Prize", "3rd Prize"]:
            if p in prizes and prizes[p]:
                await msg.edit_text(f"🎬 **Rendering {p} video...**")
                await asyncio.sleep(0.5) # Yield to update message on Telegram
                out_path = os.path.join(DOWNLOAD_DIR, f"{p.replace(' ', '_')}.mp4")
                
                render_bang_video(p, prizes[p][0], lottery_title, out_path)
                video_files.append(out_path)
                
                await msg.edit_text(f"🚀 **Uploading {p} video...**")
                await message.reply_video(video=out_path, caption=f"🏆 **{p}**")

        # 2. 4th, 5th, 6th (Slow Scroll)
        for p in ["4th Prize", "5th Prize", "6th Prize"]:
            if p in prizes and prizes[p]:
                await msg.edit_text(f"🎬 **Rendering {p} video...**")
                await asyncio.sleep(0.5)
                out_path = os.path.join(DOWNLOAD_DIR, f"{p.replace(' ', '_')}.mp4")
                
                render_scroll_video(p, prizes[p], lottery_title, out_path, is_long=False)
                video_files.append(out_path)
                
                await msg.edit_text(f"🚀 **Uploading {p} video...**")
                await message.reply_video(video=out_path, caption=f"🏅 **{p}**")

        # 3. 7th, 8th, 9th (Long Scroll)
        for p in ["7th Prize", "8th Prize", "9th Prize"]:
            if p in prizes and prizes[p]:
                await msg.edit_text(f"🎬 **Rendering {p} video...**")
                await asyncio.sleep(0.5)
                out_path = os.path.join(DOWNLOAD_DIR, f"{p.replace(' ', '_')}.mp4")
                
                render_scroll_video(p, prizes[p], lottery_title, out_path, is_long=True)
                video_files.append(out_path)
                
                await msg.edit_text(f"🚀 **Uploading {p} video...**")
                await message.reply_video(video=out_path, caption=f"🏅 **{p}**")

        await msg.edit_text("🗜️ **Compressing and combining all videos via FFmpeg...**")
        await asyncio.sleep(0.5)
        compress_and_combine(video_files, FINAL_OUTPUT_VIDEO)
        
        await msg.edit_text("🚀 **Uploading final combined HD video...**")
        await message.reply_video(video=FINAL_OUTPUT_VIDEO, caption=f"🎟️ **{lottery_title}**\nCombined Prize Draw Render.")
        
        await msg.delete()
        if os.path.exists(FINAL_OUTPUT_VIDEO): 
            os.remove(FINAL_OUTPUT_VIDEO)
        gc.collect()

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

st.title("Kerala Lottery Video Generator 🎬")
st.write("Bot is running. Send `/generate` to build, upload, and compress the pipeline progressively.")

