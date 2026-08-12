import streamlit as st
import asyncio
import threading
import re
import gc
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


# --- HTTP HELPER ---
def http_get(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if USE_CURL_CFFI:
        return cffi_requests.get(url, impersonate="chrome")
    return standard_requests.get(url, headers=headers)


# --- 1. SCRAPING & PARSING LOGIC ---

def fetch_last_10_draws():
    """Scrapes main page table (0.txt) and returns the top 10 lottery draws."""
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
    """Scrapes individual result page (1.txt) and extracts ONLY winning numbers."""
    try:
        res = http_get(target_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        post_body = soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse lottery result page body."

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
            ("1st Prize", "1st Prize"),
            ("Consolation Prize", "Consolation Prize"),
            ("2nd Prize", "2nd Prize"),
            ("3rd Prize", "3rd Prize"),
            ("4th Prize", "4th Prize"),
            ("5th Prize", "5th Prize"),
            ("6th Prize", "6th Prize"),
            ("7th Prize", "7th Prize"),
            ("8th Prize", "8th Prize"),
            ("9th Prize", "9th Prize")
        ]

        stop_phrases = [
            "verify the winning numbers", "government gazette",
            "repeated draw numbers", "tomorrow draw details",
            "previous results", "share this", "facebook", "twitter",
            "frequently asked questions", "a total of", "agent's commission"
        ]

        prizes_data = {}
        current_prize_key = None

        for line in lines:
            line_lower = line.lower()

            # Stop parsing immediately when footer/disclaimer sections are reached
            if any(sp in line_lower for sp in stop_phrases):
                current_prize_key = None
                continue

            # Detect Prize Header
            matched_header = None
            for search_str, key_name in prize_headers:
                if search_str.lower() in line_lower:
                    matched_header = key_name
                    break

            if matched_header:
                current_prize_key = matched_header
                if current_prize_key not in prizes_data:
                    prizes_data[current_prize_key] = []
                continue

            # Strict extraction based on active prize category
            if current_prize_key:
                # 1st, 2nd, 3rd Prize: Look for Ticket Series + 6 Digits + Optional District
                if current_prize_key in ["1st Prize", "2nd Prize", "3rd Prize"]:
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line):
                        prizes_data[current_prize_key].append(line)

                # Consolation Prize: Look for Series + 6 Digits
                elif current_prize_key == "Consolation Prize":
                    if re.search(r'^[A-Z]{2}\s*\d{6}', line):
                        prizes_data[current_prize_key].append(line)

                # 4th to 9th Prize: Extract ONLY 4-digit numbers
                elif current_prize_key in ["4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]:
                    four_digits = re.findall(r'\b\d{4}\b', line)
                    if four_digits:
                        prizes_data[current_prize_key].extend(four_digits)

        # Build clean output
        output = [
            f"🎟️ **{clean_title}**",
            f"📅 **Date:** `{draw_date}`",
            f"🔢 **Series:** `{series_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        prize_order = [
            ("1st Prize", "🏆"),
            ("Consolation Prize", "🎁"),
            ("2nd Prize", "🥈"),
            ("3rd Prize", "🥉"),
            ("4th Prize", "4️⃣"),
            ("5th Prize", "5️⃣"),
            ("6th Prize", "6️⃣"),
            ("7th Prize", "7️⃣"),
            ("8th Prize", "8️⃣"),
            ("9th Prize", "9️⃣")
        ]

        for p_name, emoji in prize_order:
            if p_name in prizes_data and prizes_data[p_name]:
                vals = prizes_data[p_name]
                if p_name in ["4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"]:
                    formatted_val = "  ".join(vals)
                else:
                    formatted_val = "\n".join(vals)
                output.append(f"{emoji} **{p_name}**\n`{formatted_val}`\n")

        return "\n".join(output)

    except Exception as e:
        return f"❌ Error parsing results: {str(e)}"
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

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("🔎 **Fetching today's lottery result...**")
        draws = fetch_last_10_draws()
        
        if not draws:
            await msg.edit_text("❌ Could not retrieve lottery list from main page.")
            return

        result_text = parse_lottery_result_page(draws[0]['url'])
        chunks = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]
        
        try:
            for chunk in chunks:
                await message.reply_text(chunk)
                await asyncio.sleep(1.5)
            await msg.delete()
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            await msg.edit_text(f"❌ Error: {str(e)}")
        finally:
            gc.collect()

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

    async def process_date_request(message_or_query, date_key_str: str):
        target_date = date_key_str.replace('_', '-')
        
        if hasattr(message_or_query, 'edit_message_text'):
            msg = await message_or_query.edit_message_text(f"🔎 **Fetching results for {target_date}...**")
        else:
            msg = await message_or_query.reply_text(f"🔎 **Fetching results for {target_date}...**")

        draws = fetch_last_10_draws()
        target_url = None
        
        for d in draws:
            if d['date'] == target_date:
                target_url = d['url']
                break

        if not target_url:
            target_url = f"https://www.keralalotteries.net/search?q={target_date}"

        result_text = parse_lottery_result_page(target_url)
        chunks = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]

        try:
            for chunk in chunks:
                if hasattr(message_or_query, 'message'):
                    await message_or_query.message.reply_text(chunk)
                else:
                    await message_or_query.reply_text(chunk)
                await asyncio.sleep(1.5)
            await msg.delete()
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            await msg.edit_text(f"❌ Error: {str(e)}")
        finally:
            gc.collect()

    @app.on_message(filters.regex(r"^/get_(\d{2}_\d{2}_\d{4})") & filters.private)
    async def handle_get_command(client, message):
        date_key = message.text.strip().replace("/get_", "")
        await process_date_request(message, date_key)

    @app.on_callback_query(filters.regex(r"^get_(\d{2}_\d{2}_\d{4})"))
    async def handle_get_callback(client, callback_query):
        await callback_query.answer()
        date_key = callback_query.data.replace("get_", "")
        await process_date_request(callback_query, date_key)

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
st.write("Pyrofork bot active with `/generate` and `/gencustom` commands.")
