import streamlit as st
import asyncio
import threading
import re
import gc
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
def fetch_lottery_results():
    base_url = "https://www.keralalotteries.net/?m=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        # Request homepage using curl_cffi if available, else standard requests
        if USE_CURL_CFFI:
            res = cffi_requests.get(base_url, impersonate="chrome")
        else:
            res = standard_requests.get(base_url, headers=headers)
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        today_link = None
        
        # Search for today's lottery result link
        for a in soup.find_all('a', href=True):
            if re.search(r'/\d{4}/\d{2}/.*kerala-lottery-result.*\.html', a['href']):
                today_link = a['href']
                break
                
        if not today_link:
            return "❌ Couldn't find today's result link on the homepage."

        # Request today's specific draw result page
        if USE_CURL_CFFI:
            page_res = cffi_requests.get(today_link, impersonate="chrome")
        else:
            page_res = standard_requests.get(today_link, headers=headers)
            
        page_soup = BeautifulSoup(page_res.text, 'html.parser')
        
        # Target main content section
        post_body = page_soup.find('div', id=re.compile(r'post-body-'))
        if not post_body:
            return "❌ Could not parse the result body."
            
        raw_text = post_body.get_text(separator='\n', strip=True)
        lines = raw_text.split('\n')
        
        # Filter out Agent details and live drawing placeholders (...)
        clean_lines = []
        for line in lines:
            line_str = str(line).strip()
            if "Agent Name" in line_str or "Agency No" in line_str or line_str == "...":
                continue
            if line_str: 
                clean_lines.append(line_str)
                
        return "\n".join(clean_lines)

    except Exception as e:
        return f"❌ Scraping error: {str(e)}"
    finally:
        # Free memory immediately on Python 3.14
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
        engine_name = "curl_cffi (Chrome Impersonation)" if USE_CURL_CFFI else "standard requests"
        await message.reply_text(
            f"👋 **Welcome to the Live Kerala Lottery Bot!**\n\n"
            f"Engine: `{engine_name}`\n"
            f"Use `/generate` to fetch today's results. (Draw updates live from 3:00 PM to 4:00 PM)."
        )

    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("🔎 **Fetching live Kerala Lottery results...**")
        
        results = fetch_lottery_results()
        
        # Chunk text to respect Telegram's 4096-character limit
        chunks = [results[i:i+4000] for i in range(0, len(results), 4000)]
        
        try:
            for chunk in chunks:
                await message.reply_text(f"`{chunk}`")
                # Sleep to strictly prevent Telegram FloodWait limits
                await asyncio.sleep(1.5) 
            await msg.delete()
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_text(f"⏳ Rate limited by Telegram. Resumed after {e.value}s.")
        except Exception as e:
            await msg.edit_text(f"❌ Error sending data:\n\n{str(e)}")
        finally:
            gc.collect()

    await app.start()
    try:
        # Infinite software pause bypassing OS signal crashes on secondary threads
        await asyncio.Event().wait()
    finally:
        await app.stop()


# --- 3. STREAMLIT THREADING & UI ---
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        # Clean event loop creation for Python 3.14
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_pyrofork_bot())

    bot_thread = threading.Thread(target=run_async_loop, daemon=True)
    bot_thread.start()
    return bot_thread

# Initialize background Pyrofork thread
start_bot_thread()

# Streamlit Interface
st.title("Kerala Lottery Bot 🍀")
st.write("Running in background on Python 3.14 & Streamlit Cloud.")
