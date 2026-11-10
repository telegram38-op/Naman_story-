import os
import subprocess
import requests
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
EMAIL = os.getenv("SITE_EMAIL")
PASSWORD = os.getenv("SITE_PASSWORD")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.namanstorybook.in/",
    "Content-Type": "application/json"
})

async def safe_edit(message, text):
    try:
        if message.text != text:
            await message.edit_text(text)
    except MessageNotModified:
        pass
    except Exception:
        pass

def login_to_site():
    login_urls = [
        "https://www.namanstorybook.in/api/auth/login",
        "https://www.namanstorybook.in/api/login"
    ]
    payload = {"email": EMAIL, "password": PASSWORD}
    for url in login_urls:
        try:
            res = session.post(url, json=payload, timeout=12)
            if res.status_code in [200, 201]:
                return True
        except Exception:
            pass
    return False

app = Client("naman_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
STORY_STORE = {}

def fetch_all_stories():
    url = "https://www.namanstorybook.in/api/stories"
    try:
        res = session.get(url, timeout=12)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else data.get("stories", [])
    except Exception:
        pass
    return []

def get_audio_url(episode_id):
    api_url = f"https://www.namanstorybook.in/api/episodes/{episode_id}/audio-url"
    res = session.get(api_url, timeout=15)
    if res.status_code == 401:
        if login_to_site():
            res = session.get(api_url, timeout=15)

    if res.status_code == 200:
        try:
            d = res.json()
            if isinstance(d, dict):
                return d.get("audioUrl") or d.get("url") or d.get("audio_url")
            return res.text.strip('"')
        except Exception:
            return res.text.strip('"')
    return None

def download_file(url, out_path):
    with session.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
    return out_path

def convert_to_m4a_compressed(input_file, output_m4a):
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-c:a", "aac", "-b:a", "64k",
            "-vn", output_m4a
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_m4a
    except Exception:
        return input_file

def get_audio_duration_seconds(file_path):
    try:
        if file_path.endswith(".m4a"):
            audio = MP4(file_path)
            return int(audio.info.length)
        elif file_path.endswith(".mp3"):
            audio = MP3(file_path)
            return int(audio.info.length)
    except Exception:
        pass
    return 0

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text("🎧 Story ka naam bhejiye, main audio episodes download ke liye de dunga.")

@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_search(client, message):
    query = message.text.strip().lower()
    status = await message.reply_text("🔍 Search kiya ja raha hai...")

    stories = fetch_all_stories()
    matches = [s for s in stories if query in s.get("title", "").lower() or query in s.get("slug", "").lower()]

    if not matches:
        await safe_edit(status, f"❌ '{message.text.strip()}' naam ki story nahi mili.")
        return

    buttons = []
    for s in matches[:10]:
        s_id = s.get("id")
        STORY_STORE[s_id] = s
        label = s.get("title") + (f" ({s.get('category')})" if s.get('category') else "")
        buttons.append([InlineKeyboardButton(label, callback_data=f"sel_{s_id}")])

    await status.delete()
    await message.reply_text(
        f"**Search Result For...**\n`{message.text.strip()}`\n\n👇 Story select karein:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^sel_"))
async def handle_story_click(client, callback_query):
    try:
        await callback_query.answer("Episodes load ho rahe hain...")
    except Exception:
        pass

    story_id = callback_query.data.split("_")[1]
    story = STORY_STORE.get(story_id)
    if not story:
        return

    title = story.get("title", "Story")
    category = story.get("category", "")
    cover_image = story.get("coverImage")
    episodes = story.get("episodes", [])

    if not episodes:
        try:
            r = session.get(f"https://www.namanstorybook.in/api/series/{story_id}", timeout=10)
            if r.status_code == 200:
                episodes = r.json().get("episodes", [])
        except Exception:
            pass

    buttons, row = [], []
    for idx, ep in enumerate(episodes, start=1):
        ep_id = ep.get("id") if isinstance(ep, dict) else str(ep)
        row.append(InlineKeyboardButton(f"Ep {idx}", callback_data=f"ep_{ep_id}_{idx}_{story_id}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    caption = f"📖 **Title:** {title}\n🏷️ **Category:** {category}\n🔢 **Total Episodes:** {len(episodes)}\n\n👇 Episode download karein:"
    if cover_image:
        await callback_query.message.reply_photo(photo=cover_image, caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await callback_query.message.reply_text(text=caption, reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^ep_"))
async def handle_episode_download(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass

    parts = callback_query.data.split("_")
    ep_id, ep_num = parts[1], parts[2]
    story_id = parts[3] if len(parts) > 3 else None
    
    story = STORY_STORE.get(story_id, {})
    story_title = story.get("title", "Naman Story")

    status = await callback_query.message.reply_text(f"⏳ Episode {ep_num} fetch ho raha hai...")

    audio_url = get_audio_url(ep_id)
    if not audio_url:
        await safe_edit(status, f"❌ Episode {ep_num} link generate nahi ho saka.")
        return

    raw_file = f"temp_{callback_query.id}.mp3"
    m4a_file = f"Episode_{ep_num}.m4a"

    try:
        await safe_edit(status, f"⬇️ Downloading Episode {ep_num}...")
        download_file(audio_url, raw_file)

        await safe_edit(status, "⚡ Compressing to M4A (64kbps)...")
        final_file = convert_to_m4a_compressed(raw_file, m4a_file)

        duration_sec = get_audio_duration_seconds(final_file)
        mins, secs = divmod(duration_sec, 60)
        duration_text = f"{mins:02d}:{secs:02d}"

        size_mb = os.path.getsize(final_file) / (1024 * 1024)

        await safe_edit(status, f"⬆️ Uploading ({size_mb:.1f} MB | {duration_text})...")
        await callback_query.message.reply_audio(
            audio=final_file,
            title=f"Episode {ep_num}",
            performer=story_title,
            duration=duration_sec,
            caption=f"🎵 **{story_title} - Ep {ep_num}**\n⏱ **Duration:** `{duration_text}`\n📦 **Size:** `{size_mb:.2f} MB`"
        )
        await status.delete()

    except Exception as e:
        await safe_edit(status, f"⚠️ Error: {str(e)}")

    finally:
        for f in [raw_file, m4a_file]:
            if os.path.exists(f):
                os.remove(f)

login_to_site()
print(">>> Fast M4A Downloader Bot is READY!")
app.run()
