import streamlit as st
import asyncio
import threading
import re
import gc
import io
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

# --- Python 3.14 Safe HTTP Engine Import ---
try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests as standard_requests
    USE_CURL_CFFI = False

# --- ALPHABET TO MALAYALAM PHONETICS ---
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
    """Converts ticket 'DF 319327 (VADAKARA)' to 'ഡി , എഫ് , മൂന്ന് , ഒന്ന് ... (VADAKARA)'."""
    match_series = re.match(r'^([A-Z]{2})\s*(\d{6})(.*)$', ticket_str)
    if match_series:
        series = match_series.group(1)
        number = match_series.group(2)
        extra = match_series.group(3).strip()

        s_parts = [ALPHA_TO_ML.get(c, c) for c in series]
        n_parts = [DIGITS_TO_ML.get(d, d) for d in number]
        
        combined = " , ".join(s_parts + n_parts)
        if extra:
            combined += f" {extra}"
        return combined
    else:
        # It's a 4-digit number
        n_parts = [DIGITS_TO_ML.get(d, d) for d in ticket_str]
        return " , ".join(n_parts)


# --- HTTP HELPER ---
def http_get(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if USE_CURL_CFFI:
        return cffi_requests.get(url, impersonate="chrome")
    return standard_requests.get(url, headers=headers)


# --- 1. SCRAPING & PARSING LOGIC ---
def fetch_last_10_draws():
    """Scrapes main page table and returns top 10 lottery draws."""
    base_url = "https://www.keralalotteries.net/?m=1"
    draws = []
    try:
        res = http_get(base_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            tds = row.find_all('td')
            if len(tds) >= 2:
                a_tag = row.find('a', href=True)
                row_text = row.get_text()
                date_match = re.search(r'\d{2}-\d{2}-\d{4}', row_text)
                
                if date_match and a_tag:
                    d_str = date_match.group(0)
                    url = a_tag['href']
                    title = tds[1].get_text(strip=True).replace('\n', ' ')
                    title = re.sub(r'\s*Official Result$', '', title, flags=re.IGNORECASE)
                    if not any(d['date'] == d_str for d in draws):
                        draws.append({'date': d_str, 'title': title, 'url': url})
                        
            if len(draws) >= 10:
                break
        return draws
    except Exception:
        return []
    finally:
        gc.collect()


def parse_lottery_result_page(target_url: str):
    """Scrapes individual result page and returns (Text Message String, TTS Txt File String)."""
    try:
        res = http_get(target_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        post_body = soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse lottery result page body.", None

        full_text = post_body.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]

        # Extract Header Details
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

        # Strictest cutoff: The moment any of these hit, we stop parsing lines entirely.
        hard_stop_phrases = [
            "prize winners are advised to verify", "government gazette",
            "tomorrow draw details", "previous results", "share this",
            "result (today) date:"
        ]

        prizes_data = {}
        prize_headings = {}
        current_prize_key = None

        for line in lines:
            line_lower = line.lower()

            # HARD STOP to eliminate noise (Social links, footer text, etc.)
            if any(sp in line_lower for sp in hard_stop_phrases):
                break

            matched_header = None
            for ph in prize_headers:
                if ph.lower() in line_lower:
                    matched_header = ph
                    break

            if matched_header:
                current_prize_key = matched_header
                if current_prize_key not in prizes_data:
                    prizes_data[current_prize_key] = []
                    heading_clean = re.sub(r'\s+', ' ', line).strip()
                    # Format as: "1st Prize - Rs.1,00,00,000/-"
                    heading_clean = re.sub(r'(' + re.escape(matched_header) + r')\s*(Rs\.)', r'\1 - \2', heading_clean, flags=re.IGNORECASE)
                    prize_headings[current_prize_key] = heading_clean
                continue

            # Strict capture of ticket numbers ONLY
            if current_prize_key:
                if (line.startswith("(") and line.endswith(")")) or line == "..." or line == "---":
                    continue

                if current_prize_key in ["1st Prize", "2nd Prize", "3rd Prize", "Consolation Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line):
                        prizes_data[current_prize_key].append(line)

                elif current_prize_key in ["4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]:
                    # Prevent scraping random text. Extract 4 digits only.
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    if four_digits:
                        prizes_data[current_prize_key].extend(four_digits)

        # --- 1. BUILD REGULAR TELEGRAM MESSAGE ---
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
                if p_key in ["4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]:
                    formatted_val = "  ".join(vals)
                else:
                    formatted_val = "\n".join(vals)
                msg_output.append(f"{emoji} **{heading_text}**\n`{formatted_val}`\n")

        final_msg_text = "\n".join(msg_output)

        # --- 2. BUILD TTS .TXT FILE CONTENT (1st to 6th Prize) ---
        tts_order = [
            ("1st Prize", "🏆"), ("Consolation Prize", "🎁"), ("2nd Prize", "🥈"),
            ("3rd Prize", "🥉"), ("4th Prize", "4️⃣"), ("5th Prize", "5️⃣"), ("6th Prize", "6️⃣")
        ]

        tts_output = []
        for p_key, emoji in tts_order:
            if p_key in prizes_data and prizes_data[p_key]:
                heading_text = prize_headings.get(p_key, p_key)
                tts_output.append(f"{emoji} {heading_text}")
                
                for item in prizes_data[p_key]:
                    # Process and add comma-separated TTS format
                    converted = to_tts_format(item)
                    tts_output.append(converted)
                tts_output.append("") # Empty line for spacing

        final_tts_text = "\n".join(tts_output)

        return final_msg_text, final_tts_text, draw_date

    except Exception as e:
        return f"❌ Error parsing results: {str(e)}", None, None
    finally:
        gc.collect()


# --- 2. ASYNC PYROFORK BOT ---
async def run_pyrofork_bot():
    app = Client(
        "lottery_bot",
        api_id=st.secrets["API_ID"],
        api_hash=st.secrets["API_HASH"],
        bot_token=st.secrets["BOT_TOKEN"]
    )

    @app.on_message(filters.command("start") & filters.private)
    async def handle_start(client, message):
        welcome_msg = (
            "👋 **Welcome to Kerala Lottery Results Bot!**\n\n"
            "**Available Commands:**\n"
            "• `/generate` - Fetch today's live results\n"
            "• `/gencustom` - Select from the last 10 draw dates\n"
            "• `/start` - Show this menu"
        )
        await message.reply_text(welcome_msg)

    async def execute_result_delivery(message_or_query, target_url: str):
        """Helper to send the message chunks AND the TTS file"""
        is_query = hasattr(message_or_query, 'edit_message_text')
        
        if is_query:
            msg = await message_or_query.edit_message_text("🔎 **Fetching and Formatting Results...**")
            chat_id = message_or_query.message.chat.id
        else:
            msg = await message_or_query.reply_text("🔎 **Fetching and Formatting Results...**")
            chat_id = message_or_query.chat.id

        result_text, tts_text, draw_date = parse_lottery_result_page(target_url)

        if not tts_text: # Means an error occurred
            await msg.edit_text(result_text)
            return

        # 1. Send the Main Text Result (Chunked)
        chunks = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]
        try:
            for chunk in chunks:
                await app.send_message(chat_id, chunk)
                await asyncio.sleep(1.5)
            await msg.delete()
            
            # 2. Send the TTS .txt file
            if tts_text.strip():
                tts_bytes = tts_text.encode('utf-8')
                tts_file = io.BytesIO(tts_bytes)
                tts_file.name = f"TTS_{draw_date}.txt"
                
                await app.send_document(
                    chat_id=chat_id,
                    document=tts_file,
                    caption=f"🗣️ **Malayalam Pronunciation (for TTS)**\n📅 `{draw_date}`"
                )

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            await app.send_message(chat_id, f"❌ Error sending data: {str(e)}")
        finally:
            gc.collect()

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        draws = fetch_last_10_draws()
        if not draws:
            await message.reply_text("❌ Could not retrieve lottery list from main page.")
            return
        await execute_result_delivery(message, draws[0]['url'])

    @app.on_message(filters.command("gencustom") & filters.private)
    async def handle_gencustom(client, message):
        msg = await message.reply_text("⏳ **Fetching last 10 draw dates...**")
        draws = fetch_last_10_draws()
        
        if not draws:
            await msg.edit_text("❌ Failed to fetch draw history.")
            return

        text_lines = ["📅 **Select a date to view lottery results:**\n"]
        keyboard_buttons = []

        for item in draws:
            d_str = item['date']
            cmd_date = d_str.replace('-', '_')
            title = item['title']
            
            text_lines.append(f"• **{d_str}** - {title}\n  👉 `/get_{cmd_date}`\n")
            keyboard_buttons.append([
                InlineKeyboardButton(f"📅 {d_str} | {title[:20]}...", callback_data=f"get_{cmd_date}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        await message.reply_text("\n".join(text_lines), reply_markup=reply_markup)
        await msg.delete()

    @app.on_message(filters.regex(r"^/get_(\d{2}_\d{2}_\d{4})") & filters.private)
    async def handle_get_command(client, message):
        date_key = message.text.strip().replace("/get_", "")
        target_date = date_key.replace('_', '-')
        
        draws = fetch_last_10_draws()
        target_url = next((d['url'] for d in draws if d['date'] == target_date), None)
        if not target_url:
            target_url = f"https://www.keralalotteries.net/search?q={target_date}"
            
        await execute_result_delivery(message, target_url)

    @app.on_callback_query(filters.regex(r"^get_(\d{2}_\d{2}_\d{4})"))
    async def handle_get_callback(client, callback_query):
        await callback_query.answer()
        date_key = callback_query.data.replace("get_", "")
        target_date = date_key.replace('_', '-')
        
        draws = fetch_last_10_draws()
        target_url = next((d['url'] for d in draws if d['date'] == target_date), None)
        if not target_url:
            target_url = f"https://www.keralalotteries.net/search?q={target_date}"
            
        await execute_result_delivery(callback_query, target_url)

    await app.start()
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()

# --- 3. STREAMLIT THREADING & UI ---
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_pyrofork_bot())

    bot_thread = threading.Thread(target=run_async_loop, daemon=True)
    bot_thread.start()
    return bot_thread

start_bot_thread()

st.title("Kerala Lottery Bot 🍀")
st.write("Pyrofork bot active with pure text message (1-9) and .txt document TTS generation (1-6).")
