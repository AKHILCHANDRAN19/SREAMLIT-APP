import os
import math
import random
import numpy as np
import cv2
import subprocess
import wave
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# ==========================================
# CONFIGURATION & PATHS (UPDATED FOR YOUR GITHUB)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WIDTH, HEIGHT = 1920, 1080
FPS = 30

FONTS = {
    "malayalam": os.path.join(BASE_DIR, "AnekMalayalam-Bold.ttf"),
    "english_bold": os.path.join(BASE_DIR, "Montserrat-Bold.ttf"),
    "english_extrabold": os.path.join(BASE_DIR, "Montserrat-ExtraBold.ttf")
}

def load_font(font_key, size):
    path = FONTS.get(font_key)
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except:
            pass
    if os.path.exists(FONTS["malayalam"]):
        try:
            return ImageFont.truetype(FONTS["malayalam"], size)
        except:
            pass
    return ImageFont.load_default()

def get_audio_duration(audio_path):
    try:
        with wave.open(audio_path, 'rb') as f:
            return f.getnframes() / float(f.getframerate())
    except:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            stdout=subprocess.PIPE, text=True
        )
        return float(res.stdout.strip())

# ==========================================
# 1. EASING & UTILITIES
# ==========================================
def ease_out_expo(x):
    return 1.0 if x >= 1.0 else 1.0 - math.pow(2, -10 * x)

def ease_out_back(x):
    c1 = 2.0
    c3 = c1 + 1
    x = min(x, 1.0)
    return 1.0 + c3 * math.pow(x - 1, 3) + c1 * math.pow(x - 1, 2)

def ease_drop_bounce(t):
    t = min(t, 1.0)
    if t < (1 / 2.75):
        return 7.5625 * t * t
    elif t < (2 / 2.75):
        t -= (1.5 / 2.75)
        return 7.5625 * t * t + 0.75
    elif t < (2.5 / 2.75):
        t -= (2.25 / 2.75)
        return 7.5625 * t * t + 0.9375
    else:
        t -= (2.625 / 2.75)
        return 7.5625 * t * t + 0.984375

def apply_opacity(image, opacity):
    if opacity >= 1.0: return image
    if opacity <= 0.0: return Image.new("RGBA", image.size, (0, 0, 0, 0))
    arr = np.array(image).astype(np.float32)
    arr[:, :, 3] = arr[:, :, 3] * opacity
    return Image.fromarray(arr.astype(np.uint8), "RGBA")

def generate_vertical_gradient(w, h, stops):
    gradient = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / float(h - 1 if h > 1 else 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                range_t = (t - stops[i][0]) / (stops[i + 1][0] - stops[i][0])
                c1, c2 = np.array(stops[i][1]), np.array(stops[i + 1][1])
                c = c1 + (c2 - c1) * range_t
                gradient[y, :] = [int(c[0]), int(c[1]), int(c[2]), 255]
                break
    return Image.fromarray(gradient, mode="RGBA")

# ==========================================
# 2. VECTOR ICONS (ACCURATE & CRISP)
# ==========================================
def draw_like_icon(draw, cx, cy, size=32, fill_color=(255, 215, 0, 255)):
    draw.rounded_rectangle([cx - size*0.9, cy - size*0.25, cx - size*0.55, cy + size*0.75], radius=size*0.08, fill=fill_color)
    draw.rounded_rectangle([cx - size*0.45, cy - size*0.1, cx + size*0.8, cy + size*0.75], radius=size*0.12, fill=fill_color)
    draw.polygon([
        (cx - size*0.45, cy - size*0.05),
        (cx - size*0.15, cy - size*0.85),
        (cx + size*0.2, cy - size*0.85),
        (cx + size*0.1, cy - size*0.1)
    ], fill=fill_color)
    draw.ellipse([cx - size*0.22, cy - size*0.9, cx + size*0.22, cy - size*0.5], fill=fill_color)

def draw_bell_icon(draw, cx, cy, size=32, fill_color=(255, 75, 95, 255)):
    draw.ellipse([cx - size*0.2, cy - size*0.85, cx + size*0.2, cy - size*0.5], outline=fill_color, width=max(2, int(size*0.1)))
    draw.polygon([
        (cx - size*0.4, cy - size*0.5),
        (cx + size*0.4, cy - size*0.5),
        (cx + size*0.75, cy + size*0.35),
        (cx - size*0.75, cy + size*0.35)
    ], fill=fill_color)
    draw.ellipse([cx - size*0.42, cy - size*0.65, cx + size*0.42, cy - size*0.3], fill=fill_color)
    draw.rounded_rectangle([cx - size*0.85, cy + size*0.3, cx + size*0.85, cy + size*0.5], radius=size*0.08, fill=fill_color)
    draw.ellipse([cx - size*0.22, cy + size*0.45, cx + size*0.22, cy + size*0.75], fill=fill_color)

def generate_whatsapp_badge(radius=45):
    size = radius * 4
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    cx, cy = size // 2, size // 2
    r = size * 0.40
    
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(37, 211, 102, 255))
    tail = [
        (cx - r * 0.70, cy + r * 0.45),
        (cx - r * 1.02, cy + r * 1.02),
        (cx - r * 0.32, cy + r * 0.80)
    ]
    draw.polygon(tail, fill=(37, 211, 102, 255))
    
    handset = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(handset)
    h_draw.rounded_rectangle([cx - 20, cy - 56, cx + 20, cy - 20], radius=10, fill=(255, 255, 255, 255))
    h_draw.rounded_rectangle([cx - 20, cy + 20, cx + 20, cy + 56], radius=10, fill=(255, 255, 255, 255))
    h_draw.rounded_rectangle([cx - 20, cy - 42, cx - 2, cy + 42], radius=7, fill=(255, 255, 255, 255))
    
    rotated = handset.rotate(-45, resample=Image.Resampling.BICUBIC, center=(cx, cy))
    badge.alpha_composite(rotated)
    
    target_dim = radius * 2 + 10
    return badge.resize((target_dim, target_dim), Image.Resampling.LANCZOS)

# ==========================================
# 3. ASSET PRE-RENDERING ENGINE
# ==========================================
def pre_render_news_background():
    bg_arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(185 - (ratio * 70))
        g = int(12 + (ratio * 10))
        b = int(24 + (ratio * 15))
        bg_arr[y, :] = [b, g, r]
        
    cv2.rectangle(bg_arr, (0, 0), (WIDTH, 75), (252, 252, 252), -1)
    cv2.line(bg_arr, (0, 75), (WIDTH, 75), (0, 0, 205), 5)

    ticker_y = HEIGHT - 75
    cv2.rectangle(bg_arr, (0, ticker_y - 12), (WIDTH, ticker_y), (0, 210, 255), -1)
    cv2.rectangle(bg_arr, (0, ticker_y), (WIDTH, HEIGHT), (255, 255, 255), -1)
    
    bg_rgba = cv2.cvtColor(bg_arr, cv2.COLOR_BGR2RGBA)
    canvas = Image.fromarray(bg_rgba, mode="RGBA")
    
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([WIDTH//2 - 750, HEIGHT//2 - 250, WIDTH//2 + 750, HEIGHT//2 + 250], fill=(255, 60, 40, 55))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(130)))
    
    return canvas

def pre_render_hero_title():
    font = load_font("malayalam", 130)
    text = "കേരള സംസ്ഥാന ഭാഗ്യക്കുറി"
    
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH // 2, 430
    
    bbox = draw.textbbox((cx, cy), text, font=font, anchor="mm")
    text_y_start, text_height = int(bbox[1]), int(bbox[3] - bbox[1])
    
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((cx, cy + 22), text, font=font, fill=(0, 0, 0, 245), anchor="mm")
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    
    for i in range(16, 0, -1):
        draw.text((cx, cy + i), text, font=font, fill=(70, 15, 0, 255), anchor="mm")
        
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).text((cx, cy), text, font=font, fill=255, anchor="mm")
    
    stops = [
        (0.0, (255, 255, 235)),
        (0.25, (255, 220, 30)),
        (0.70, (255, 150, 0)),
        (1.0, (180, 65, 0))
    ]
    grad = generate_vertical_gradient(WIDTH, max(text_height, 10), stops)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grad_layer.paste(grad, (0, text_y_start))
    layer.paste(grad_layer, (0, 0), mask)
    
    draw.text((cx, cy), text, font=font, fill=None, outline=(255, 245, 170, 255), stroke_width=3, anchor="mm")
    return layer

def pre_render_gold_ribbon():
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = WIDTH // 2, 605
    
    font = load_font("malayalam", 74)
    txt = "ഇന്നത്തെ നറുക്കെടുപ്പ് ഫലങ്ങൾ"
    
    bbox = draw.textbbox((cx, cy), txt, font=font, anchor="mm")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    ribbon_w = text_w + 140
    ribbon_h = text_h + 40
    
    x1, y1 = cx - ribbon_w // 2, cy - ribbon_h // 2
    x2, y2 = cx + ribbon_w // 2, cy + ribbon_h // 2
    
    mask_c = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask_c).rounded_rectangle([x1, y1, x2, y2], radius=22, fill=255)
    stops = [
        (0.0, (255, 248, 190)),
        (0.2, (255, 215, 0)),
        (0.8, (230, 140, 0)),
        (1.0, (160, 70, 0))
    ]
    grad = generate_vertical_gradient(WIDTH, int(ribbon_h), stops)
    grad_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grad_layer.paste(grad, (0, int(y1)))
    layer.paste(grad_layer, (0, 0), mask_c)
    
    draw.rounded_rectangle([x1, y1, x2, y2], radius=22, outline=(255, 240, 150, 255), width=3)
    draw.text((cx, cy + 2), txt, font=font, fill=(60, 10, 0, 255), stroke_width=2, stroke_fill=(255, 240, 150, 255), anchor="mm") 
    
    shadow = layer.copy().filter(ImageFilter.GaussianBlur(16))
    shadow_data = np.array(shadow)
    shadow_data[..., :3] = 0
    final = Image.fromarray(shadow_data)
    final.alpha_composite(layer)
    return final

def pre_render_scene2_engagement():
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    f1 = load_font("malayalam", 70)
    
    txt1 = "ലൈക് & ഷെയർ"
    bb1 = draw.textbbox((0, 0), txt1, font=f1)
    tw1, th1 = bb1[2] - bb1[0], bb1[3] - bb1[1]
    
    icon_w = 40
    gap = 25
    content1_w = icon_w + gap + tw1
    card1_w = content1_w + 100
    card1_h = max(th1, icon_w) + 60
    
    txt2 = "സബ്സ്ക്രൈബ്"
    bb2 = draw.textbbox((0, 0), txt2, font=f1)
    tw2, th2 = bb2[2] - bb2[0], bb2[3] - bb2[1]
    
    content2_w = icon_w + gap + tw2
    card2_w = content2_w + 100
    card2_h = max(th2, icon_w) + 60
    
    card_gap = 50
    total_w = card1_w + card_gap + card2_w
    c1_x1 = (WIDTH - total_w) // 2
    c1_y1 = 535 - card1_h // 2
    c1_x2 = c1_x1 + card1_w
    c1_y2 = c1_y1 + card1_h
    
    c2_x1 = c1_x2 + card_gap
    c2_y1 = 535 - card2_h // 2
    c2_x2 = c2_x1 + card2_w
    c2_y2 = c2_y1 + card2_h
    
    draw.rounded_rectangle([c1_x1, c1_y1, c1_x2, c1_y2], radius=24, fill=(35, 10, 20, 225), outline=(255, 215, 0, 220), width=4)
    draw.rounded_rectangle([c1_x1+2, c1_y1+2, c1_x2-2, c1_y2-2], radius=22, outline=(255, 255, 255, 90), width=2)
    
    c1_content_start = c1_x1 + (card1_w - content1_w) // 2
    draw_like_icon(draw, cx=c1_content_start + icon_w//2, cy=535, size=34, fill_color=(255, 215, 0, 255))
    draw.text((c1_content_start + icon_w + gap, 535), txt1, font=f1, fill="#FFFFFF", anchor="lm")
    
    draw.rounded_rectangle([c2_x1, c2_y1, c2_x2, c2_y2], radius=24, fill=(45, 8, 15, 230), outline=(255, 60, 80, 230), width=4)
    draw.rounded_rectangle([c2_x1+2, c2_y1+2, c2_x2-2, c2_y2-2], radius=22, outline=(255, 255, 255, 100), width=2)
    
    c2_content_start = c2_x1 + (card2_w - content2_w) // 2
    draw_bell_icon(draw, cx=c2_content_start + icon_w//2, cy=535, size=34, fill_color=(255, 75, 95, 255))
    draw.text((c2_content_start + icon_w + gap, 535), txt2, font=f1, fill="#FFD700", anchor="lm")
    
    return layer

def pre_render_scene3_whatsapp():
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    f_main = load_font("malayalam", 86)
    f_btn = load_font("malayalam", 65)
    
    txt_main = "വാട്സ്ആപ്പ് ചാനലിൽ"
    txt_btn = "ഇപ്പോൾ തന്നെ ജോയിൻ ചെയ്യുക"
    
    btn_bb = draw.textbbox((0, 0), txt_btn, font=f_btn)
    btn_tw, btn_th = btn_bb[2] - btn_bb[0], btn_bb[3] - btn_bb[1]
    btn_w = btn_tw + 140
    btn_h = btn_th + 42
    
    btn_x1 = WIDTH // 2 - btn_w // 2
    btn_y1 = 565
    btn_x2 = WIDTH // 2 + btn_w // 2
    btn_y2 = btn_y1 + btn_h
    
    card_w = max(btn_w, 1100) + 160
    card_h = 580
    card_bounds = [WIDTH//2 - card_w//2, 235, WIDTH//2 + card_w//2, 235 + card_h]
    
    draw.rounded_rectangle(card_bounds, radius=32, fill=(12, 28, 18, 235), outline=(37, 211, 102, 240), width=5)
    draw.rounded_rectangle([card_bounds[0]+3, card_bounds[1]+3, card_bounds[2]-3, card_bounds[3]-3], radius=29, outline=(255, 215, 0, 170), width=2)
    
    top_badge = [WIDTH//2 - 300, card_bounds[1] - 25, WIDTH//2 + 300, card_bounds[1] + 35]
    draw.rounded_rectangle(top_badge, radius=18, fill=(255, 195, 0, 255), outline=(255, 255, 255, 220), width=2)
    draw.text((WIDTH//2, card_bounds[1] + 5), "• FAST RESULTS & UPDATES •", font=load_font("english_extrabold", 24), fill=(40, 15, 0, 255), anchor="mm")
    
    wa_logo = generate_whatsapp_badge(radius=42)
    layer.alpha_composite(wa_logo, (WIDTH//2 - wa_logo.width//2, 305))
    
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((WIDTH//2, 450), txt_main, font=f_main, fill=(37, 211, 102, 160), anchor="mm")
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16)))
    
    draw.text((WIDTH//2, 453), txt_main, font=f_main, fill=(0, 0, 0, 220), anchor="mm")
    draw.text((WIDTH//2, 450), txt_main, font=f_main, fill="#FFFFFF", anchor="mm")
    
    draw.rounded_rectangle([btn_x1, btn_y1, btn_x2, btn_y2], radius=25, fill=(37, 211, 102, 255), outline=(255, 255, 255, 240), width=3)
    draw.text((WIDTH//2, (btn_y1 + btn_y2)//2), txt_btn, font=f_btn, fill=(10, 40, 15, 255), anchor="mm")
    
    f_sub = load_font("english_bold", 26)
    draw.text((WIDTH//2, 740), "• LINK IN DESCRIPTION & ABOUT SECTION •", font=f_sub, fill="#A8D0B5", anchor="mm")
    
    return layer

def pre_render_ticker():
    font = load_font("english_bold", 38)
    ticker_text = "   FASTEST LOTTERY RESULTS   •   KERALA STATE LOTTERY OFFICIAL   •   SUBSCRIBE FOR LIVE UPDATES   •   JOIN WHATSAPP FOR INSTANT PDF   •"
    
    dummy = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), ticker_text, font=font)
    w = bbox[2] - bbox[0] + 50
    h = 75
    
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((25, h // 2), ticker_text, font=font, fill=(15, 15, 15, 255), anchor="lm")
    return img

# ==========================================
# 4. MASTER COMPOSITING ENGINE
# ==========================================
def generate_video(output_video_path):
    # Select a random audio track from 1.wav to 8.wav inside the 'Intro' folder
    random_audio_name = f"{random.randint(1, 8)}.wav"
    audio_path = os.path.join(BASE_DIR, "Intro", random_audio_name)
    
    print(f"[*] Reading audio duration from: {audio_path}")
    total_duration = get_audio_duration(audio_path)
    total_frames = int(total_duration * FPS)
    print(f"[*] Total Duration: {total_duration:.2f}s | Frames: {total_frames}")

    print("[*] Pre-rendering Studio Assets...")
    bg_asset = pre_render_news_background()
    hero_asset = pre_render_hero_title()
    hero_alpha_mask = hero_asset.split()[3]
    ribbon_asset = pre_render_gold_ribbon()
    scene2_asset = pre_render_scene2_engagement()
    scene3_asset = pre_render_scene3_whatsapp()
    ticker_asset = pre_render_ticker()
    ticker_w = ticker_asset.width
    
    header_font = load_font("english_bold", 36)
    
    t_scene1_end = total_duration * 0.36
    t_scene2_end = total_duration * 0.64
    
    card_glitters = [
        {'x': 320, 'y': 235, 'phase': random.uniform(0, 6), 'speed': 0.16},
        {'x': 1600, 'y': 235, 'phase': random.uniform(0, 6), 'speed': 0.14},
        {'x': 320, 'y': 815, 'phase': random.uniform(0, 6), 'speed': 0.18},
        {'x': 1600, 'y': 815, 'phase': random.uniform(0, 6), 'speed': 0.15},
    ]
    
    confetti = []
    confetti_triggered = False

    print("[*] Initializing Fast FFmpeg Stream...")
    cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{WIDTH}x{HEIGHT}', '-pix_fmt', 'bgr24', '-r', str(FPS),
        '-i', '-', '-i', audio_path, '-c:v', 'libx264', '-preset', 'ultrafast',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-ac', '2',
        '-shortest', output_video_path
    ]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    print("[*] Rendering Frames...")
    
    for frame_idx in range(total_frames):
        time_sec = frame_idx / FPS
        canvas = bg_asset.copy()
        draw = ImageDraw.Draw(canvas)
        
        shake_dx, shake_dy = 0, 0
        flash_alpha = 0

        draw.text((50, 38), "KERALA STATE LOTTERY • OFFICIAL BROADCAST", font=header_font, fill=(200, 10, 20, 255), anchor="lm")
        
        if int(time_sec * 2) % 2 == 0:
            draw.ellipse([WIDTH - 220, 28, WIDTH - 200, 48], fill=(220, 0, 0, 255))
            draw.text((WIDTH - 190, 38), "LIVE", font=header_font, fill=(20, 20, 20, 255), anchor="lm")

        # SCENE 1
        if time_sec <= t_scene1_end:
            hp = min(time_sec / 0.35, 1.0)
            op = ease_out_expo(hp)
            hy = int(140 - (30 * (1 - op)))
            
            draw.rounded_rectangle([WIDTH//2 - 400, hy - 28, WIDTH//2 + 400, hy + 28], radius=15, fill=(35, 10, 18, int(225*op)), outline=(255, 215, 0, int(190*op)), width=2)
            draw.text((WIDTH//2, hy), "GOVERNMENT OF KERALA • OFFICIAL RESULTS", font=load_font("english_bold", 24), fill=(255, 240, 190, int(255*op)), anchor="mm")

            if time_sec > 0.2:
                rp = min((time_sec - 0.2) / 0.35, 1.0)
                scale_r = ease_out_back(rp)
                if scale_r > 0.01:
                    w = max(int(WIDTH * scale_r), 1)
                    resized_ribbon = ribbon_asset.resize((w, HEIGHT), Image.Resampling.BILINEAR)
                    temp = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                    temp.paste(resized_ribbon, (int((WIDTH - w) // 2), 0))
                    canvas.alpha_composite(apply_opacity(temp, min(scale_r, 1.0)))

            impact_t = 0.50
            if time_sec >= 0.25:
                sp = min((time_sec - 0.25) / (impact_t - 0.25), 1.0)
                scale_h = 4.5 - (ease_out_expo(sp) * 3.5)
                
                w, h = max(int(WIDTH * scale_h), 1), max(int(HEIGHT * scale_h), 1)
                resized_hero = hero_asset.resize((w, h), Image.Resampling.BILINEAR)
                temp = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                temp.paste(resized_hero, (int((WIDTH - w) // 2), int((HEIGHT - h) // 2)))
                canvas.alpha_composite(apply_opacity(temp, min(sp * 2.5, 1.0)))

            if time_sec >= impact_t:
                if not confetti_triggered:
                    confetti_triggered = True
                    colors = [(255, 215, 0), (255, 255, 255), (255, 80, 0), (255, 200, 100), (0, 220, 255)]
                    for _ in range(160):
                        angle = random.uniform(0, 2 * math.pi)
                        speed = random.uniform(15, 50)
                        confetti.append({
                            'x': WIDTH // 2, 'y': 430,
                            'vx': math.cos(angle) * speed,
                            'vy': math.sin(angle) * speed - 16,
                            'col': random.choice(colors),
                            'size': random.randint(4, 12),
                            'life': 1.0
                        })
                
                frames_since_impact = int((time_sec - impact_t) * FPS)
                if frames_since_impact < 5:
                    intensity = int(22 - (frames_since_impact * 4))
                    shake_dx = random.randint(-intensity, intensity)
                    shake_dy = random.randint(-intensity, intensity)
                    if frames_since_impact == 0:
                        flash_alpha = 180

                if 0.7 <= time_sec <= 1.35:
                    beam_prog = (time_sec - 0.7) / 0.65
                    bx = int(100 + (1600 * beam_prog))
                    
                    beam_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                    b_draw = ImageDraw.Draw(beam_layer)
                    poly = [(bx + 120, 0), (bx + 320, 0), (bx - 120, HEIGHT), (bx - 320, HEIGHT)]
                    b_draw.polygon(poly, fill=(255, 255, 255, 190))
                    beam_layer = beam_layer.filter(ImageFilter.GaussianBlur(15))
                    
                    masked_beam = beam_layer.copy()
                    masked_beam.putalpha(ImageChops.multiply(beam_layer.split()[3], hero_alpha_mask))
                    canvas.alpha_composite(masked_beam)

        # SCENE 2
        elif time_sec <= t_scene2_end:
            local_t = (time_sec - t_scene1_end) / (t_scene2_end - t_scene1_end)
            
            draw.rounded_rectangle([WIDTH//2 - 340, 250, WIDTH//2 + 340, 330], radius=20, fill=(35, 10, 20, 225), outline=(255, 215, 0, 200), width=3)
            draw.text((WIDTH//2, 290), "SUPPORT OUR CHANNEL", font=load_font("english_extrabold", 30), fill="#FFD700", anchor="mm")
            
            punch_prog = min(local_t * 3.5, 1.0)
            scale_s2 = ease_out_back(punch_prog)
            
            if scale_s2 > 0.01:
                w = max(int(WIDTH * scale_s2), 1)
                h = max(int(HEIGHT * scale_s2), 1)
                resized_s2 = scene2_asset.resize((w, h), Image.Resampling.BILINEAR)
                temp = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                temp.paste(resized_s2, (int((WIDTH - w) // 2), int((HEIGHT - h) // 2)))
                canvas.alpha_composite(apply_opacity(temp, min(scale_s2, 1.0)))

        # SCENE 3
        else:
            local_t = (time_sec - t_scene2_end) / (total_duration - t_scene2_end)
            
            drop_prog = ease_drop_bounce(min(local_t * 3.0, 1.0))
            drop_y = int(-HEIGHT + (drop_prog * HEIGHT))
            
            temp = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            temp.paste(scene3_asset, (0, drop_y))
            canvas.alpha_composite(temp)

            if local_t > 0.3:
                glitter_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                g_draw = ImageDraw.Draw(glitter_layer)
                
                for g in card_glitters:
                    g['phase'] += g['speed']
                    pulse = (math.sin(g['phase']) + 1) / 2
                    s = int(6 + 26 * pulse)
                    g_op = int(60 + 195 * pulse)
                    ray_col = (255, 235, 120, g_op)
                    core_col = (255, 255, 255, g_op)
                    
                    g_draw.line([(g['x'] - s, g['y']), (g['x'] + s, g['y'])], fill=ray_col, width=3)
                    g_draw.line([(g['x'], g['y'] - s), (g['x'], g['y'] + s)], fill=ray_col, width=3)
                    g_draw.ellipse([g['x'] - 4, g['y'] - 4, g['x'] + 4, g['y'] + 4], fill=core_col)
                    
                canvas.alpha_composite(glitter_layer.filter(ImageFilter.GaussianBlur(3)))
                canvas.alpha_composite(glitter_layer)

        if confetti:
            c_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            c_draw = ImageDraw.Draw(c_layer)
            active_confetti = False
            for p in confetti:
                if p['life'] > 0:
                    active_confetti = True
                    p['x'] += p['vx']
                    p['y'] += p['vy']
                    p['vy'] += 2.2
                    p['life'] -= 0.022
                    cop = int(255 * max(p['life'], 0.0))
                    px, py = int(p['x']), int(p['y'])
                    s = int(p['size'])
                    c_draw.rectangle([px - s, py - s // 2, px + s, py + s // 2], fill=p['col'] + (cop,))
            if active_confetti:
                canvas.alpha_composite(c_layer)

        if flash_alpha > 0:
            flash_layer = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, flash_alpha))
            canvas.alpha_composite(flash_layer)

        ticker_speed = 300
        offset = int((time_sec * ticker_speed) % ticker_w)
        ticker_y = HEIGHT - 75
        
        canvas.alpha_composite(ticker_asset, (-offset, ticker_y))
        canvas.alpha_composite(ticker_asset, (-offset + ticker_w, ticker_y))
        if WIDTH > ticker_w:
            canvas.alpha_composite(ticker_asset, (-offset + ticker_w * 2, ticker_y))

        final_frame = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        final_frame.paste(canvas, (int(shake_dx), int(shake_dy)))

        bgr_frame = cv2.cvtColor(np.array(final_frame), cv2.COLOR_RGBA2BGR)
        process.stdin.write(bgr_frame.tobytes())

    print("\n[*] Finalizing Video & Muxing Audio...")
    process.stdin.close()
    process.wait()
    print(f"\n[SUCCESS] Authentic Broadcast Intro Saved to: {output_video_path}")

if __name__ == "__main__":
    generate_video(os.path.join(BASE_DIR, "renders", "Intro.mp4"))
