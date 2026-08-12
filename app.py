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
                    # Clean up title suffix
                    title = re.sub(r'\s*Official Result$', '', title, flags=re.IGNORECASE)
                    
                    if not any(d['date'] == d_str for d in draws):
                        draws.append({'date': d_str, 'title': title, 'url': url})
                        
            if len(draws) >= 10:
                break
                
        return draws
    except Exception as e:
        return []
    finally:
        gc.collect()


def parse_lottery_result_page(target_url: str):
    """Scrapes individual result page (1.txt) and extracts formatted prizes."""
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
        lottery_name = h1_tag.get_text(strip=True) if h1_tag else "Kerala Lottery Result"
        lottery_name = re.sub(r'Official|Result|Today', '', lottery_name, flags=re.IGNORECASE).strip()

        date_match = re.search(r'Date of Draw:\s*(\d{1,2}[/-]\d{2}[/-]\d{4})', full_text)
        if not date_match:
            date_match = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', lottery_name)
        draw_date = date_match.group(1).replace('/', '-') if date_match else "N/A"

        series_match = re.search(r'Today Lottery Series:\s*([A-Z0-9,\s]+)', full_text)
        series_str = series_match.group(1).strip() if series_match else "N/A"

        # Noise filters to exclude
        noise_keywords = [
            "Kerala State Lotteries Results Official", "കേരള സംസ്ഥാന ഭാഗ്യക്കുറി",
            "Check Winning List", "Prize Details", "one of the seven weekly lotteries",
            "108 lakh tickets were issued", "Next Upcoming Bumper", "Thiruvonam Bumper",
            "Gorky Bhavan", "Near Bakery Junction", "KERALA LOTTERY TODAY RESULT",
            "Today LIVE Kerala Lottery Result", "ഇന്നത്തെ കേരളാ ലോട്ടറി",
            "തത്സമയ നറുക്കെടുപ്പ്", "Winners Numbers", "Agent Name", "Agency No",
            "The prize winners are advised to verify", "Next Dhanalekshmi", "Next Sthree",
            "Repeated Draw Numbers", "Tomorrow draw details", "Kerala Lotteries Releases",
            "Previous Lottery Results", "Back to HOME", "Share This", "Frequently Asked Questions",
            "At which time does", "What is a Lottery", "Is online lottery permitted",
            "Can Kerala Lottery be purchased", "Who is the authority", "Is it mandatory",
            "PDF Images", "---", "For The Tickets Ending with The Following Numbers"
        ]

        prize_headers = [
            "1st Prize", "Consolation Prize", "2nd Prize", "3rd Prize",
            "4th Prize", "5th Prize", "6th Prize", "7th Prize", "8th Prize", "9th Prize"
        ]

        prizes = {}
        current_prize = None

        for line in lines:
            if any(nk.lower() in line.lower() for nk in noise_keywords):
                continue
            
            matched_header = None
            for ph in prize_headers:
                if ph.lower() in line.lower():
                    matched_header = ph
                    break
            
            if matched_header:
                current_prize = matched_header
                if current_prize not in prizes:
                    prizes[current_prize] = []
                continue

            if current_prize:
                if (line.startswith("(") and line.endswith(")")) or line == "..." or line == "---":
                    continue
                prizes[current_prize].append(line)

        # Build clean formatted Telegram output
        output = [
            f"🎟️ **{lottery_name}**",
            f"📅 **Date:** `{draw_date}`",
            f"🔢 **Series:** `{series_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        prize_emojis = {
            "1st Prize": "🏆", "Consolation Prize": "🎁", "2nd Prize": "🥈",
            "3rd Prize": "🥉", "4th Prize": "4️⃣", "5th Prize": "5️⃣",
            "6th Prize": "6️⃣", "7th Prize": "7️⃣", "8th Prize": "8️⃣", "9th Prize": "9️⃣"
        }

        for prize_name, numbers in prizes.items():
            emoji = prize_emojis.get(prize_name, "⭐")
            formatted_numbers = "\n".join(numbers) if numbers else "Awaiting Draw..."
            output.append(f"{emoji} **{prize_name}**\n`{formatted_numbers}`\n")

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

        # Top item is today's draw
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
            
            # Clickable command link format in Telegram
            text_lines.append(f"• **{d_str}** - {title}\n  👉 `/get_{cmd_date}`\n")
            
            # Interactive Inline Keyboard Button
            keyboard_buttons.append([
                InlineKeyboardButton(f"📅 {d_str} | {title[:20]}...", callback_data=f"get_{cmd_date}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        await message.reply_text("\n".join(text_lines), reply_markup=reply_markup)
        await msg.delete()

    # --- DYNAMIC DATE COMMAND & CALLBACK HANDLERS ---
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
            # Direct search on site if not in top 10
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
