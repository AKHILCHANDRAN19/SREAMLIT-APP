import os
import cv2
import numpy as np
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080

# Multi-environment font fallback (Streamlit Cloud, Local, Termux)
FONT_SEARCH_PATHS = [
    os.path.join(BASE_DIR, "Montserrat-Black.ttf"),
    os.path.join(BASE_DIR, "Montserrat-ExtraBold.ttf"),
    os.path.join(BASE_DIR, "Montserrat-Bold.ttf"),
    os.path.join(BASE_DIR, "Anton-Regular.ttf"),
    "/storage/emulated/0/Download/Montserrat-Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/system/fonts/Roboto-Bold.ttf"
]

FONT_PATH = None
for p in FONT_SEARCH_PATHS:
    if os.path.exists(p):
        FONT_PATH = p
        break

def get_font(size):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, int(size))
        except Exception:
            pass
    return ImageFont.load_default()

def get_fitted_font(text, max_w, initial_size, min_size=20):
    size = initial_size
    while size > min_size:
        font = get_font(size)
        bbox = font.getbbox(text)
        w = bbox[2] - bbox[0]
        if w <= max_w:
            return font, size
        size -= 2
    return get_font(min_size), min_size

# -------------------------------------------------------------------------
# 1. Dark Textured Studio Background with Optical Ambient Lighting
# -------------------------------------------------------------------------
def make_textured_background(w, h):
    y, x = np.ogrid[:h, :w]
    cx, cy = w * 0.5, h * 0.45
    dist = np.sqrt(((x - cx) / (w * 0.65)) ** 2 + ((y - cy) / (h * 0.55)) ** 2)
    dist = np.clip(dist, 0.0, 1.0)
    
    # Smooth studio spotlight (Charcoal center fading to deep obsidian)
    vignette = 0.5 * (1.0 + np.cos(dist * np.pi))
    c_center = np.array([40, 40, 46], dtype=np.float32)
    c_edge   = np.array([12, 12, 14], dtype=np.float32)
    
    bg = c_edge[None, None, :] + (c_center - c_edge)[None, None, :] * vignette[:, :, None]
    
    # Premium subtle grain
    noise = np.random.normal(0, 1.8, (h, w, 3))
    bg = np.clip(bg + noise, 0, 255).astype(np.uint8)
    base_img = Image.fromarray(bg).convert("RGBA")

    # Ambient Studio Key Light Blooms
    bloom_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bloom_layer)
    bd.ellipse([w // 2 - 460, 310 - 150, w // 2 + 460, 310 + 150], fill=(255, 170, 30, 40))
    bd.ellipse([w // 2 - 500, 525 - 150, w // 2 + 500, 525 + 150], fill=(200, 220, 255, 28))
    bloom_layer = bloom_layer.filter(ImageFilter.GaussianBlur(75))

    return Image.alpha_composite(base_img, bloom_layer)

# -------------------------------------------------------------------------
# 2. 3D Extrusion & Chamfer Bevel Engine
# -------------------------------------------------------------------------
def render_3d_text(
    text, 
    pos, 
    font, 
    depth=26, 
    front_top=(255, 255, 255), 
    front_bot=(215, 215, 220),
    depth_top=(45, 45, 48), 
    depth_bot=(18, 18, 20),
    highlight_color=(255, 255, 255)
):
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.text(pos, text, font=font, fill=255, anchor="mm")
    
    mask_np = np.array(mask)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_np = cv2.dilate(mask_np, k, iterations=1)
    mask = Image.fromarray(mask_np)

    # Extrusion Slices
    extrusion = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    slice_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(slice_img)

    for step in range(depth, 0, -1):
        t = step / float(depth)
        r = int(depth_top[0] * (1.0 - t) + depth_bot[0] * t)
        g = int(depth_top[1] * (1.0 - t) + depth_bot[1] * t)
        b = int(depth_top[2] * (1.0 - t) + depth_bot[2] * t)

        # Reuse single pre-allocated slice buffer
        sd.rectangle([0, 0, W, H], fill=(0, 0, 0, 0))
        sd.bitmap((0, step), mask, fill=(r, g, b, 255))
        extrusion = Image.alpha_composite(extrusion, slice_img)

    del slice_img

    # Front Gradient
    bbox = mask.getbbox()
    min_y, max_y = (bbox[1], bbox[3]) if bbox else (0, H)
    h_box = max(max_y - min_y, 1)

    front = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad_arr = np.zeros((H, W, 4), dtype=np.uint8)
    
    for y_idx in range(min_y, min(max_y + 1, H)):
        t = (y_idx - min_y) / float(h_box)
        r = int(front_top[0] * (1.0 - t) + front_bot[0] * t)
        g = int(front_top[1] * (1.0 - t) + front_bot[1] * t)
        b = int(front_top[2] * (1.0 - t) + front_bot[2] * t)
        grad_arr[y_idx, :] = [r, g, b, 255]

    grad_img = Image.fromarray(grad_arr, "RGBA")
    front.paste(grad_img, (0, 0), mask=mask)

    # Top Edge Highlight Rim
    highlight = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.bitmap((0, -2), mask, fill=(*highlight_color, 165))
    highlight.paste((0, 0, 0, 0), (0, 0), mask=mask)
    front = Image.alpha_composite(front, highlight)

    return mask, extrusion, front

# -------------------------------------------------------------------------
# 3. Dynamic Thumbnail Generation
# -------------------------------------------------------------------------
def generate_thumbnail(lottery_name, draw_date, out_path):
    canvas = make_textured_background(W, H)
    MAX_HERO_WIDTH = 1580

    header_text = "KERALA LOTTERY RESULT"
    lottery_text = lottery_name.upper().strip()
    date_text = draw_date.strip()
    cta_text = "WATCH FULL RESULT"

    try:
        d = datetime.strptime(draw_date, "%d-%m-%Y")
        day_name = d.strftime("%A").upper()
        live_text = f"{day_name} RESULT"
    except Exception:
        live_text = "TODAY RESULT"

    font_hdr, _  = get_fitted_font(header_text, MAX_HERO_WIDTH, initial_size=110)
    font_name, _ = get_fitted_font(lottery_text, MAX_HERO_WIDTH, initial_size=155)
    font_date, _ = get_fitted_font(date_text, MAX_HERO_WIDTH, initial_size=195)
    font_cta, _  = get_fitted_font(cta_text, 750, initial_size=54)
    font_live, _ = get_fitted_font(live_text, 700, initial_size=52)
    font_tag     = get_font(32)
    font_icon    = get_font(42)

    # 1. HEADER (3D Silver) @ Y = 135
    m_h, e_h, f_h = render_3d_text(
        text=header_text,
        pos=(W // 2, 135),
        font=font_hdr,
        depth=22,
        front_top=(255, 255, 255),
        front_bot=(195, 205, 218),
        depth_top=(45, 50, 60),
        depth_bot=(15, 18, 22),
        highlight_color=(255, 255, 255)
    )

    # 2. LOTTERY NAME (3D 24K Gold) @ Y = 310
    m_n, e_n, f_n = render_3d_text(
        text=lottery_text,
        pos=(W // 2, 310),
        font=font_name,
        depth=30,
        front_top=(255, 225, 25),      # Radiant Gold
        front_bot=(240, 130, 0),       # Deep Amber
        depth_top=(55, 36, 12),
        depth_bot=(16, 10, 4),
        highlight_color=(255, 252, 210)
    )

    # 3. DATE (3D Polished Silver / Chrome) @ Y = 525
    m_d, e_d, f_d = render_3d_text(
        text=date_text,
        pos=(W // 2, 525),
        font=font_date,
        depth=32,
        front_top=(255, 255, 255),
        front_bot=(185, 195, 210),
        depth_top=(48, 54, 64),
        depth_bot=(16, 18, 24),
        highlight_color=(255, 255, 255)
    )

    # Ambient Drop Shadows
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.bitmap((0, 24), m_h, fill=(0, 0, 0, 200))
    sd.bitmap((0, 30), m_n, fill=(0, 0, 0, 220))
    sd.bitmap((0, 34), m_d, fill=(0, 0, 0, 220))
    
    canvas = Image.alpha_composite(canvas, shadow_layer.filter(ImageFilter.GaussianBlur(28)))
    canvas = Image.alpha_composite(canvas, shadow_layer.filter(ImageFilter.GaussianBlur(8)))

    # Composite 3D Text
    for ext, front in [(e_h, f_h), (e_n, f_n), (e_d, f_d)]:
        canvas = Image.alpha_composite(canvas, ext)
        canvas = Image.alpha_composite(canvas, front)

    # 4. CTA BUTTON: "WATCH FULL RESULT" @ Y = 685
    cta_bbox = font_cta.getbbox(cta_text)
    cta_txt_w = cta_bbox[2] - cta_bbox[0]
    btn_w = cta_txt_w + 220
    btn_h = 100
    bx1, by1 = (W - btn_w) // 2, 685
    bx2, by2 = bx1 + btn_w, by1 + btn_h
    btn_cy = (by1 + by2) // 2

    btn_shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bsd = ImageDraw.Draw(btn_shadow)
    bsd.rounded_rectangle([bx1, by1 + 8, bx2, by2 + 8], radius=50, fill=(0, 0, 0, 210))
    canvas = Image.alpha_composite(canvas, btn_shadow.filter(ImageFilter.GaussianBlur(14)))

    btn_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(btn_layer)
    bd.rounded_rectangle([bx1, by1, bx2, by2], radius=50, fill=(16, 16, 20, 245), outline=(255, 204, 0, 255), width=4)
    bd.text((W // 2, btn_cy), cta_text, font=font_cta, fill=(255, 255, 255, 255), anchor="mm")
    bd.text((W // 2 - cta_txt_w // 2 - 42, btn_cy), "▶", font=font_icon, fill=(255, 204, 0, 255), anchor="mm")
    bd.text((W // 2 + cta_txt_w // 2 + 42, btn_cy), "◀", font=font_icon, fill=(255, 204, 0, 255), anchor="mm")
    canvas = Image.alpha_composite(canvas, btn_layer)

    # 5. LIVE BROADCAST CAPSULE @ Y = 855
    live_bbox = font_live.getbbox(live_text)
    live_txt_w = live_bbox[2] - live_bbox[0]

    tag_w, tag_h = 150, 60
    gap, pad_h = 26, 28
    box_w = pad_h + tag_w + gap + live_txt_w + pad_h
    box_h = 96
    
    lx1 = (W - box_w) // 2
    ly1 = 855
    lx2, ly2 = lx1 + box_w, ly1 + box_h
    ly_cy = (ly1 + ly2) // 2

    live_shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lsd = ImageDraw.Draw(live_shadow)
    lsd.rounded_rectangle([lx1, ly1 + 6, lx2, ly2 + 6], radius=28, fill=(0, 0, 0, 200))
    canvas = Image.alpha_composite(canvas, live_shadow.filter(ImageFilter.GaussianBlur(12)))

    live_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(live_layer)
    ld.rounded_rectangle([lx1, ly1, lx2, ly2], radius=28, fill=(14, 14, 18, 245), outline=(255, 255, 255, 180), width=3)

    # Red "LIVE" Badge Box
    tx1, ty1 = lx1 + pad_h, ly_cy - (tag_h // 2)
    tx2, ty2 = tx1 + tag_w, ty1 + tag_h
    ld.rounded_rectangle([tx1, ty1, tx2, ty2], radius=14, fill=(230, 25, 25, 255))
    
    tag_cy = (ty1 + ty2) // 2
    dot_x = tx1 + 24
    ld.ellipse([dot_x - 6, tag_cy - 6, dot_x + 6, tag_cy + 6], fill=(255, 255, 255, 255))
    ld.text((tx1 + 82, tag_cy), "LIVE", font=font_tag, fill=(255, 255, 255, 255), anchor="mm")

    # Day Result Text (Gold)
    txt_x = tx2 + gap
    ld.text((txt_x, ly_cy), live_text, font=font_live, fill=(255, 215, 0, 255), anchor="lm")
    canvas = Image.alpha_composite(canvas, live_layer)

    # Save Output PNG
    final_output = canvas.convert("RGB")
    final_output.save(out_path, "PNG", quality=100)
    return out_path
