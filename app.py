import streamlit as st
import asyncio
import threading
import re
import gc
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.errors import FloodWait

# --- Python 3.14 Safe HTTP Engine Import ---
try:
    from curl_cffi import requests as cffi_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests as standard_requests
    USE_CURL_CFFI = False


# --- 1. SCRAPING LOGIC ---
def fetch_today_lottery_result():
    # Get current date in Kerala Time (IST: UTC + 5:30)
    ist = timezone(timedelta(hours=5, minutes=30))
    today_date = datetime.now(ist).strftime("%d-%m-%Y")
    
    base_url = "https://www.keralalotteries.net/?m=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        # Step A: Request the main homepage (0.txt)
        if USE_CURL_CFFI:
            res = cffi_requests.get(base_url, impersonate="chrome")
        else:
            res = standard_requests.get(base_url, headers=headers)
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        target_link = None
        lottery_title = None

        # Step B: Match today's date in the "Kerala Lottery Draw Results Chart" table
        rows = soup.find_all('tr')
        for row in rows:
            row_text = row.get_text()
            if today_date in row_text:
                links = row.find_all('a', href=True)
                if links:
                    target_link = links[-1]['href']
                    lottery_title = links[-1].get_text(strip=True)
                    break

        # Fallback: If today's exact row is not yet published in the chart, grab the latest result link
        if not target_link:
            for row in rows:
                links = row.find_all('a', href=True)
                for a in links:
                    if re.search(r'/\d{4}/\d{2}/.*kerala-lottery-result.*\.html', a['href']):
                        target_link = a['href']
                        lottery_title = a.get_text(strip=True)
                        break
                if target_link:
                    break

        if not target_link:
            return f"❌ Result link for today ({today_date}) was not found on the main page."

        # Step C: Redirect to the lottery result page (1.txt)
        if USE_CURL_CFFI:
            page_res = cffi_requests.get(target_link, impersonate="chrome")
        else:
            page_res = standard_requests.get(target_link, headers=headers)
            
        page_soup = BeautifulSoup(page_res.text, 'html.parser')
        
        # Step D: Extract prize details from the post body
        post_body = page_soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse the lottery result content."

        lines = post_body.get_text(separator='\n', strip=True).split('\n')
        
        clean_output = []
        if lottery_title:
            clean_output.append(f"📅 Date: {today_date}")
            clean_output.append(f"🎟️ {lottery_title}")
            clean_output.append("=" * 32 + "\n")

        # Step E: Filter out Agent names, Agency numbers, and live placeholders (...)
        for line in lines:
            line_str = str(line).strip()
            
            # Stop parsing when reaching page footers / disclaimers
            if "The prize winners are advised to verify" in line_str or "Share This" in line_str:
                break
                
            # Filter out agent info and empty live draw placeholders
            if "Agent Name" in line_str or "Agency No" in line_str or line_str == "...":
                continue
                
            if line_str:
                clean_output.append(line_str)
                
        return "\n".join(clean_output)

    except Exception as e:
        return f"❌ Scraping Error: {str(e)}"
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
            "👋 **Welcome to Kerala Lottery Live Bot!**\n\n"
            "Commands:\n"
            "• `/generate` - Fetch today's 1st to 9th prize numbers & winner districts.\n"
            "• `/start` - Display this message."
        )
        await message.reply_text(welcome_msg)

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("🔎 **Searching homepage table & fetching today's results...**")
        
        results = fetch_today_lottery_result()
        
        # Split message into chunks if it exceeds Telegram's 4096 character limit
        chunks = [results[i:i+4000] for i in range(0, len(results), 4000)]
        
        try:
            for chunk in chunks:
                await message.reply_text(f"`{chunk}`")
                await asyncio.sleep(1.5)  # Avoid rate limits
            await msg.delete()
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_text(f"⏳ Telegram rate limit hit. Resuming after {e.value}s...")
        except Exception as e:
            await msg.edit_text(f"❌ Error delivering messages:\n\n{str(e)}")
        finally:
            gc.collect()

    await app.start()
    try:
        # Software event pause to keep bot running on secondary thread
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

# Start background Pyrofork bot thread
start_bot_thread()

# Streamlit App UI
st.title("Kerala Lottery Bot 🍀")
st.write("Bot is running in the background on Python 3.14.")
