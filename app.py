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
import random
from pyrogram import Client, filters

# 1. Define the ADVANCED Manim animation code
MANIM_CODE = """from manim import *
import random

class NuclearFissionFusion(Scene):
    def construct(self):
        # --- INTRO ---
        # Fixed: Text is assigned z_index=10 to guarantee it always renders on top of particles
        title = Text("Advanced Nuclear Physics", font_size=48, gradient=(RED, YELLOW)).set_z_index(10)
        subtitle = Text("Fission & Fusion Dynamics", font_size=32, color=BLUE).set_z_index(10)
        intro_group = VGroup(title, subtitle).arrange(DOWN, buff=0.5)
        
        self.play(DrawBorderThenFill(title), run_time=1.5)
        self.play(FadeIn(subtitle, shift=UP))
        self.wait(1)
        self.play(FadeOut(intro_group, shift=UP))
        
        # --- HELPER: REALISTIC NUCLEUS GENERATOR ---
        def get_nucleus(p_count, n_count, scale=1.0):
            particles = VGroup()
            for _ in range(p_count):
                particles.add(Dot(color=RED, radius=0.15 * scale).set_z_index(5))
            for _ in range(n_count):
                particles.add(Dot(color=BLUE, radius=0.15 * scale).set_z_index(5))
            
            for dot in particles:
                r = random.uniform(0, 0.4 * (p_count+n_count)**0.4 * scale)
                theta = random.uniform(0, 2 * PI)
                dot.move_to(RIGHT * r * np.cos(theta) + UP * r * np.sin(theta))
            return particles

        # --- PART 1: FISSION ---
        fission_text = Text("1. Nuclear Fission", color=YELLOW, font_size=32).to_corner(UL).set_z_index(10)
        self.play(Write(fission_text))

        # Shifted the entire reaction DOWN so it doesn't hit the top text
        u235 = get_nucleus(15, 20) 
        u235.move_to(DOWN * 0.5)
        u235_label = Text("Uranium-235", font_size=24).next_to(u235, DOWN * 2).set_z_index(10)
        
        self.play(FadeIn(u235, scale=0.5), FadeIn(u235_label))
        
        neutron = Dot(color=WHITE, radius=0.1).move_to(LEFT * 6 + DOWN * 0.5).set_z_index(5)
        n_label = Text("n", font_size=20).next_to(neutron, UP).set_z_index(10)
        n_group = VGroup(neutron, n_label)
        
        trace = TracedPath(neutron.get_center, stroke_width=3, stroke_color=YELLOW).set_z_index(4)
        self.add(trace)
        
        self.play(FadeIn(n_group))
        
        self.play(n_group.animate.move_to(u235.get_left()), run_time=1.2, rate_func=rush_into)
        self.remove(trace)
        
        self.play(
            FadeOut(n_group), 
            u235.animate.set_color(ORANGE), 
            u235_label.animate.become(Text("U-236 (Highly Unstable)", font_size=24, color=ORANGE).next_to(u235, DOWN * 2).set_z_index(10))
        )
        
        for _ in range(3):
            self.play(u235.animate.shift(RIGHT*0.1), run_time=0.1)
            self.play(u235.animate.shift(LEFT*0.2), run_time=0.1)
            self.play(u235.animate.shift(RIGHT*0.1), run_time=0.1)
            
        ba141 = get_nucleus(8, 10).move_to(u235.get_center())
        kr92 = get_nucleus(7, 10).move_to(u235.get_center())
        n1, n2, n3 = [Dot(color=WHITE, radius=0.1).move_to(u235.get_center()).set_z_index(5) for _ in range(3)]
        
        self.remove(u235, u235_label)
        self.add(ba141, kr92, n1, n2, n3)
        
        shockwave = Circle(radius=0.5, color=YELLOW, stroke_width=20).move_to(u235.get_center()).set_z_index(0)
        # Force energy text far UP to completely avoid overlaps
        energy_text = Text("Energy Released! (200 MeV)", color=YELLOW, font_size=30).to_edge(UP, buff=1.5).set_z_index(10)
        
        self.play(
            ba141.animate.shift(UP * 2.5 + LEFT * 3),
            kr92.animate.shift(DOWN * 2.5 + RIGHT * 3),
            n1.animate.shift(UP * 4 + RIGHT * 2),
            n2.animate.shift(RIGHT * 5),
            n3.animate.shift(DOWN * 4 + LEFT * 2),
            shockwave.animate.scale(20).set_opacity(0),
            FadeIn(energy_text, shift=UP),
            run_time=1.5,
            rate_func=rate_functions.ease_out_sine
        )
        self.wait(1.5)
        self.play(FadeOut(VGroup(ba141, kr92, n1, n2, n3, energy_text, fission_text)))

        # --- PART 2: FUSION ---
        fusion_text = Text("2. Nuclear Fusion", color=RED, font_size=32).to_corner(UL).set_z_index(10)
        self.play(Write(fusion_text))

        deuterium = get_nucleus(1, 1, scale=1.8).shift(LEFT * 4 + DOWN * 0.5)
        tritium = get_nucleus(1, 2, scale=1.8).shift(RIGHT * 4 + DOWN * 0.5)
        
        d_label = Text("Deuterium", font_size=24).next_to(deuterium, DOWN * 2).set_z_index(10)
        t_label = Text("Tritium", font_size=24).next_to(tritium, DOWN * 2).set_z_index(10)
        
        self.play(FadeIn(deuterium, shift=RIGHT), FadeIn(d_label), FadeIn(tritium, shift=LEFT), FadeIn(t_label))
        self.wait(0.5)

        self.play(
            deuterium.animate.move_to(DOWN * 0.5),
            tritium.animate.move_to(DOWN * 0.5),
            FadeOut(d_label, t_label),
            run_time=1.2,
            rate_func=rush_into
        )

        he4 = get_nucleus(2, 2, scale=1.8).move_to(DOWN * 0.5)
        fn = Dot(color=WHITE, radius=0.15).move_to(DOWN * 0.5).set_z_index(5)
        
        self.remove(deuterium, tritium)
        self.add(he4, fn)
        
        shockwave2 = Circle(radius=0.5, color=RED, stroke_width=25).move_to(DOWN * 0.5).set_z_index(0)
        glow = Dot(color=WHITE, radius=8, fill_opacity=0.9).move_to(DOWN * 0.5).set_z_index(2)
        
        self.add(glow)
        
        he4_label = Text("Helium-4", font_size=24).next_to(he4, DOWN * 2).set_z_index(10)
        energy_fusion = Text("Massive Energy! (17.6 MeV)", color=ORANGE, font_size=36).to_edge(UP, buff=1.5).set_z_index(10)
        
        self.play(
            glow.animate.set_opacity(0),
            shockwave2.animate.scale(25).set_opacity(0),
            he4.animate.shift(LEFT * 2.5),
            fn.animate.shift(RIGHT * 6),
            FadeIn(energy_fusion, shift=UP),
            FadeIn(he4_label),
            run_time=1.5,
            rate_func=rate_functions.ease_out_sine
        )
        self.wait(2)
        
        # --- OUTRO ---
        self.play(FadeOut(Group(*self.mobjects)))
        outro = Text("Animation Complete", font_size=40, gradient=(BLUE, GREEN)).set_z_index(10)
        self.play(Write(outro))
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
            "I am running securely in the background of a Streamlit Cloud server.\n\n"
            "**What I can do:**\n"
            "🖼️ **Send an Image:** Process with OpenCV (Canny Edge Detection).\n"
            "🎬 **`/generate`:** Render an advanced 720p HD physics animation using Manim."
        )
        await message.reply_text(welcome_msg)

    # --- HANDLER 2: 720P MANIM VIDEO GENERATION ---
    @app.on_message(filters.command("generate") & filters.private)
    async def handle_generate(client, message):
        msg = await message.reply_text("☢️ Rendering 720p HD animation via Manim engine... Please wait a few moments. ⏳")
        
        try:
            with open("nuclear_scene.py", "w") as f:
                f.write(MANIM_CODE)
            
            # Gag the obnoxious pydub syntax warnings so they don't pollute logs
            env = os.environ.copy()
            env["PYTHONWARNINGS"] = "ignore::SyntaxWarning"
            
            # -qm renders in Medium Quality (720p at 30 fps)
            command = [
                sys.executable, "-m", "manim", 
                "-qm", 
                "--progress_bar", "none",
                "nuclear_scene.py", 
                "NuclearFissionFusion", 
                "--media_dir", "./manim_media"
            ]
            process = subprocess.run(command, capture_output=True, text=True, env=env)
            
            if process.returncode != 0:
                raise Exception(f"Manim Engine Error:\n{process.stderr}")

            video_files = glob.glob("./manim_media/**/*.mp4", recursive=True)
            if not video_files:
                raise FileNotFoundError("Video file was not found after rendering.")
                
            raw_video_path = video_files[0]
            video_with_audio_path = "final_output_video.mp4"
            
            await msg.edit_text("✅ Render complete! Fixing video formatting for Telegram...")
            
            # THE GIF FIX: Use FFMPEG to inject a silent audio track into the MP4.
            # Telegram sees the audio track and treats it as a true Video with a playbar instead of a looping GIF.
            ffmpeg_cmd = [
                "ffmpeg", "-y", 
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", 
                "-i", raw_video_path, 
                "-c:v", "copy", "-c:a", "aac", "-shortest", 
                video_with_audio_path
            ]
            subprocess.run(ffmpeg_cmd, capture_output=True)

            await msg.edit_text("🚀 Uploading HD Video to Telegram...")
            
            await message.reply_video(
                video=video_with_audio_path, 
                caption="⚛️ Advanced Nuclear Fission & Fusion (720p HD)",
                supports_streaming=True # Tells Telegram clients to stream the video natively
            )
            await msg.delete()
            
        except Exception as e:
            error_str = str(e)
            if "SyntaxWarning" in error_str:
                error_str = "\n".join([line for line in error_str.split("\n") if "SyntaxWarning" not in line])
            await msg.edit_text(f"❌ An error occurred:\n\n{error_str}")
        
        finally:
            if os.path.exists("nuclear_scene.py"):
                os.remove("nuclear_scene.py")
            if os.path.exists("final_output_video.mp4"):
                os.remove("final_output_video.mp4")
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
st.write("The bot is running securely in the background.")
st.markdown("* Send an **Image** to run OpenCV Edge Detection.")
st.markdown("* Type **`/start`** to see the welcome menu.")
st.markdown("* Type **`/generate`** to render an advanced nuclear physics animation using Manim.")

