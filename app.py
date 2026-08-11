import streamlit as st
import asyncio
import threading
import cv2
import numpy as np
import gc
import os
import subprocess
import glob
import shutil
import sys
from pyrogram import Client, filters

# 1. Define the Manim animation code as a string
MANIM_CODE = """from manim import *

class NuclearFissionFusion(Scene):
    def construct(self):
        # --- INTRO ---
        title = Text("Nuclear Fission & Fusion", font_size=40)
        self.play(Write(title), run_time=2)
        self.wait(1)
        self.play(FadeOut(title))
        
        # --- PART 1: FISSION ---
        fission_title = Text("Part 1: Nuclear Fission", font_size=32).to_edge(UP)
        self.play(Write(fission_title))
        
        nucleus = VGroup(*[Dot(radius=0.15, color=BLUE if i%2==0 else RED) for i in range(15)])
        nucleus.arrange_in_grid(rows=4, cols=4).move_to(ORIGIN)
        
        neutron = Dot(radius=0.1, color=WHITE).shift(LEFT * 4)
        n_label = Text("Neutron", font_size=20).next_to(neutron, DOWN)
        n_group = VGroup(neutron, n_label)
        
        self.play(FadeIn(nucleus), FadeIn(n_group))
        self.play(n_group.animate.move_to(nucleus.get_left() + LEFT*0.1), run_time=1.5)
        self.play(FadeOut(n_group), nucleus.animate.scale(1.2).set_color(YELLOW), run_time=0.5)
        
        unstable = Text("Unstable Nucleus", font_size=24, color=YELLOW).next_to(nucleus, UP)
        self.play(Write(unstable))
        
        for _ in range(3):
            self.play(nucleus.animate.shift(RIGHT*0.1), run_time=0.1)
            self.play(nucleus.animate.shift(LEFT*0.2), run_time=0.1)
            self.play(nucleus.animate.shift(RIGHT*0.1), run_time=0.1)
            
        self.play(FadeOut(unstable))
        
        part1 = VGroup(*[Dot(radius=0.15, color=BLUE if i%2==0 else RED) for i in range(7)]).arrange_in_grid(rows=3, cols=3).move_to(nucleus.get_center())
        part2 = VGroup(*[Dot(radius=0.15, color=BLUE if i%2==0 else RED) for i in range(7)]).arrange_in_grid(rows=3, cols=3).move_to(nucleus.get_center())
        free_ns = VGroup(*[Dot(radius=0.1, color=WHITE) for _ in range(3)]).move_to(nucleus.get_center())
        
        self.remove(nucleus)
        self.add(part1, part2, free_ns)
        
        energy = Text("ENERGY RELEASED!", font_size=32, color=YELLOW)
        
        self.play(
            part1.animate.shift(LEFT * 3 + UP * 1),
            part2.animate.shift(RIGHT * 3 + DOWN * 1),
            free_ns[0].animate.shift(UP * 2),
            free_ns[1].animate.shift(RIGHT * 2 + UP * 1.5),
            free_ns[2].animate.shift(LEFT * 2 + DOWN * 2),
            FadeIn(energy),
            run_time=2
        )
        self.wait(2)
        self.play(FadeOut(part1, part2, free_ns, energy, fission_title))
        
        # --- PART 2: FUSION ---
        fusion_title = Text("Part 2: Nuclear Fusion", font_size=32).to_edge(UP)
        self.play(Write(fusion_title))
        
        d_nuc = VGroup(Dot(radius=0.15, color=RED), Dot(radius=0.15, color=BLUE)).arrange(RIGHT, buff=0.05).shift(LEFT * 3)
        t_nuc = VGroup(Dot(radius=0.15, color=RED), Dot(radius=0.15, color=BLUE), Dot(radius=0.15, color=BLUE)).arrange(RIGHT, buff=0.05).shift(RIGHT * 3)
        
        self.play(FadeIn(d_nuc), FadeIn(t_nuc))
        self.wait(1)
        
        self.play(d_nuc.animate.move_to(LEFT * 0.2), t_nuc.animate.move_to(RIGHT * 0.2), run_time=2)
        
        he_nuc = VGroup(Dot(radius=0.15, color=RED), Dot(radius=0.15, color=RED), Dot(radius=0.15, color=BLUE), Dot(radius=0.15, color=BLUE)).arrange_in_grid(rows=2, cols=2)
        extra_n = Dot(radius=0.1, color=WHITE)
        
        self.remove(d_nuc, t_nuc)
        self.add(he_nuc, extra_n)
        
        fusion_energy = Text("MASSIVE ENERGY!", font_size=36, color=ORANGE).next_to(he_nuc, UP * 2)
        
        self.play(he_nuc.animate.shift(LEFT * 2), extra_n.animate.shift(RIGHT * 4), FadeIn(fusion_energy), run_time=2)
        self.wait(2)
        
        # --- OUTRO ---
        self.play(FadeOut(he_nuc, extra_n, fusion_energy, fusion_title))
        self.play(Write(Text("Animation Complete", font_size=32)))
        self.wait(2)
"""

# 2. Define your async Pyrofork bot
async def run_pyrofork_bot():
    app = Client(
        "my_bot_session",
        api_id=st.secrets["API_ID"],
        api_hash=st.secrets["API_HASH"],
        bot_token=st.secrets["BOT_TOKEN"]
    )

    # --- HANDLER 1: THE /START COMMAND ---
    @app.on_message(filters.command("start") & filters.private)
    async def handle_start(client, message):
        welcome_msg = (
            "👋 **Welcome to the Processing Bot!**\n\n"
            "I am running in the background of a Streamlit Cloud server.\n\n"
            "**What I can do:**\n"
            "🖼️ **Send an Image:** I will process it with OpenCV (Canny Edge Detection).\n"
            "🎬 **`/generate`:** I will render a ~30s nuclear physics animation using Manim."
        )
        await message.reply_text(welcome_msg)

    # --- HANDLER 2: MANIM VIDEO GENERATION ---
    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("☢️ Initializing Manim engine... Generating animation. This will take a few minutes. ⏳")
        
        try:
            with open("nuclear_scene.py", "w") as f:
                f.write(MANIM_CODE)
            
            # The Fix: Use sys.executable instead of "python" to ensure the virtual env is used
            command = [sys.executable, "-m", "manim", "-ql", "nuclear_scene.py", "NuclearFissionFusion", "--media_dir", "./manim_media"]
            process = subprocess.run(command, capture_output=True, text=True)
            
            if process.returncode != 0:
                raise Exception(f"Manim Engine Error:\n{process.stderr}")

            video_files = glob.glob("./manim_media/videos/nuclear_scene/480p15/NuclearFissionFusion.mp4")
            if not video_files:
                raise FileNotFoundError("Video was not successfully generated.")
                
            video_path = video_files[0]
            
            await msg.edit_text("✅ Animation complete! Uploading to Telegram...")
            await message.reply_video(video=video_path, caption="⚛️ Nuclear Fission & Fusion Animation")
            await msg.delete()
            
        except Exception as e:
            await msg.edit_text(f"❌ An error occurred:\n\n{str(e)}")
        
        finally:
            if os.path.exists("nuclear_scene.py"):
                os.remove("nuclear_scene.py")
            if os.path.exists("./manim_media"):
                shutil.rmtree("./manim_media", ignore_errors=True)
            gc.collect()

    # --- HANDLER 3: OPENCV PHOTO PROCESSING ---
    @app.on_message(filters.photo & filters.private)
    async def handle_photo(client, message):
        processing_msg = await message.reply_text("Processing your image...")
        
        file_path = None
        processed_path = "output.png"
        
        try:
            file_path = await message.download()
            
            img = cv2.imread(file_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 100, 200)
            
            cv2.imwrite(processed_path, edges)
            
            await message.reply_photo(
                photo=processed_path, 
                caption="Here is the processed result!"
            )
            await processing_msg.delete()
            
            del img
            del gray
            del edges
            
        except Exception as e:
            await processing_msg.edit_text(f"An error occurred: {str(e)}")
            
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(processed_path):
                os.remove(processed_path)
            gc.collect()

    # 3. Start the bot and keep it alive safely
    await app.start()
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()

# 4. Run the bot in a background thread
@st.cache_resource
def start_bot_thread():
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_pyrofork_bot())

    bot_thread = threading.Thread(target=run_async_loop, daemon=True)
    bot_thread.start()
    return bot_thread

# 5. Execute the thread starter
start_bot_thread()

# 6. Streamlit UI
st.title("Pyrofork + Manim + CV2 Bot ⚡")
st.write("The bot is running perfectly in the background.")
st.markdown("* Send an **Image** to run OpenCV Edge Detection.")
st.markdown("* Type **`/start`** to see the welcome menu.")
st.markdown("* Type **`/generate`** to render a nuclear physics animation using Manim.")
