import os
import json
import asyncio
import subprocess
import requests
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified
from mutagen.mp4 import MP4

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "9082003026:AAGJ4cU0bQysTVqYrKn2kTkBov3Z3iQFiMM")
API_ID = int(os.getenv("API_ID", 32156800))
API_HASH = os.getenv("API_HASH", "73fbf3673dd59fd129a9937ca11c00d2")
EMAIL = os.getenv("SITE_EMAIL", "Anilk242843@gmail.com")
PASSWORD = os.getenv("SITE_PASSWORD", "ROHIT12345")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.namanstorybook.in/",
    "Content-Type": "application/json"
})

app = Client("naman_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

STORY_STORE = {}
USER_STATE = {}
TRACKER_FILE = "autoset_data.json"
TRACKER_RUNNING = False

def load_tracker():
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_tracker(data):
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
                print(">>> Site login successful!")
                return True
        except Exception:
            pass
    return False

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

def get_story_by_id_or_slug(identifier):
    stories = fetch_all_stories()
    for s in stories:
        if s.get("id") == identifier or s.get("slug") == identifier:
            return s
    try:
        r = session.get(f"https://www.namanstorybook.in/api/series/{identifier}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

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
        audio = MP4(file_path)
        return int(audio.info.length)
    except Exception:
        return 0

async def process_and_send_episode(chat_id, ep_id, ep_num, story_title, cover_url=None):
    status = await app.send_message(chat_id, f"⏳ Episode {ep_num} fetch ho raha hai...")
    audio_url = get_audio_url(ep_id)
    if not audio_url:
        await safe_edit(status, f"❌ Episode {ep_num} ka audio link nahi mila.")
        return

    raw_file = f"temp_{ep_id}.mp3"
    m4a_file = f"Episode_{ep_num}.m4a"
    thumb_file = f"thumb_{ep_id}.jpg"

    try:
        await safe_edit(status, f"⬇️ Downloading Ep {ep_num}...")
        download_file(audio_url, raw_file)

        await safe_edit(status, f"⚡ M4A 64k compression...")
        final_file = convert_to_m4a_compressed(raw_file, m4a_file)

        duration_sec = get_audio_duration_seconds(final_file)
        mins, secs = divmod(duration_sec, 60)
        duration_text = f"{mins:02d}:{secs:02d}"
        size_mb = os.path.getsize(final_file) / (1024 * 1024)

        if cover_url:
            try:
                download_file(cover_url, thumb_file)
                # Episode se pehle uski image bhejna
                await app.send_photo(
                    chat_id=chat_id,
                    photo=thumb_file,
                    caption=f"🖼️ **{story_title} - Episode {ep_num}**"
                )
            except Exception:
                pass

        await safe_edit(status, f"⬆️ Uploading Ep {ep_num}...")
        await app.send_audio(
            chat_id=chat_id,
            audio=final_file,
            title=f"Episode {ep_num}",
            performer=story_title,
            duration=duration_sec,
            thumb=thumb_file if os.path.exists(thumb_file) else None,
            caption=f"🎵 **{story_title} - Ep {ep_num}**\n⏱ **Duration:** `{duration_text}`\n📦 **Size:** `{size_mb:.2f} MB`"
        )
        await status.delete()

    except Exception as e:
        await safe_edit(status, f"⚠️ Error Ep {ep_num}: {e}")
    finally:
        for f in [raw_file, m4a_file, thumb_file]:
            if os.path.exists(f):
                os.remove(f)

async def background_auto_tracker():
    """Bina kisi extra library ke har 10 min me new episode check karega"""
    while True:
        await asyncio.sleep(600)
        try:
            tracker = load_tracker()
            for s_id, data in tracker.items():
                chat_id = data.get("chat_id")
                known_count = data.get("last_count", 0)
                story = get_story_by_id_or_slug(s_id)
                if not story:
                    continue

                episodes = story.get("episodes", [])
                total_online = len(episodes)

                if total_online > known_count:
                    new_eps = episodes[known_count:]
                    for idx, ep in enumerate(new_eps, start=known_count + 1):
                        ep_id = ep.get("id") if isinstance(ep, dict) else str(ep)
                        await app.send_message(chat_id, f"🔔 **New Episode Alert!**\n`{story.get('title')}` ka Episode {idx} aa gaya hai!")
                        await process_and_send_episode(chat_id, ep_id, idx, story.get("title"), story.get("coverImage"))

                    data["last_count"] = total_online
                    save_tracker(tracker)
        except Exception as e:
            print("Tracker error:", e)

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    await message.reply_text(
        "🎧 **Naman Story Book Bot**\n\n"
        "• Kisi bhi story ka naam bhejo (e.g. `demon`).\n"
        "• Auto update set karne ke liye: `/autoset <story_slug>`\n"
        "• Active auto-fetch dekhne ke liye: `/tracker`"
    )

@app.on_message(filters.command("autoset"))
async def autoset_cmd(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: `/autoset <story_name ya slug>`\nExample: `/autoset demon-premium`")
        return

    query = args[1].strip()
    story = get_story_by_id_or_slug(query)
    if not story:
        await message.reply_text("❌ Story nahi mili. Sahi slug ya ID daalein.")
        return

    s_id = story.get("id") or query
    episodes = story.get("episodes", [])
    
    tracker = load_tracker()
    tracker[s_id] = {
        "title": story.get("title"),
        "chat_id": message.chat.id,
        "last_count": len(episodes)
    }
    save_tracker(tracker)

    await message.reply_text(
        f"✅ **Auto-Set Activated!**\n\n"
        f"📖 **Story:** {story.get('title')}\n"
        f"🔢 **Current Episodes:** {len(episodes)}\n\n"
        f"Jab bhi naya episode aayega, bot automatically yahan bhej dega."
    )

@app.on_message(filters.command("tracker"))
async def tracker_cmd(client, message):
    tracker = load_tracker()
    if not tracker:
        await message.reply_text("Koi bhi story auto-set par nahi hai.")
        return
    text = "📋 **Active Auto-Trackers:**\n\n"
    for s_id, d in tracker.items():
        text += f"• **{d.get('title')}** (Last: {d.get('last_count')} Eps)\n"
    await message.reply_text(text)

@app.on_message(filters.text & ~filters.command(["start", "autoset", "tracker"]))
async def handle_search_or_range(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    user_id = message.from_user.id
    text = message.text.strip()

    if user_id in USER_STATE:
        state = USER_STATE[user_id]
        episodes = state["episodes"]
        story_title = state["title"]
        cover_image = state["cover"]

        ep_indices = []
        if "-" in text:
            try:
                start_ep, end_ep = map(int, text.split("-"))
                ep_indices = list(range(start_ep, min(end_ep + 1, len(episodes) + 1)))
            except Exception:
                pass
        elif text.isdigit():
            val = int(text)
            if 1 <= val <= len(episodes):
                ep_indices = [val]

        if ep_indices:
            for num in ep_indices:
                ep_data = episodes[num - 1]
                ep_id = ep_data.get("id") if isinstance(ep_data, dict) else str(ep_data)
                await process_and_send_episode(message.chat.id, ep_id, num, story_title, cover_image)
            return

    status = await message.reply_text("🔍 Search kiya ja raha hai...")
    all_stories = fetch_all_stories()
    matches = [s for s in all_stories if text.lower() in s.get("title", "").lower() or text.lower() in s.get("slug", "").lower()]

    if not matches:
        await safe_edit(status, f"❌ '{text}' naam ki story nahi mili.")
        return

    buttons = []
    for s in matches[:10]:
        s_id = s.get("id")
        STORY_STORE[s_id] = s
        label = s.get("title") + (f" ({s.get('category')})" if s.get('category') else "")
        buttons.append([InlineKeyboardButton(label, callback_data=f"sel_{s_id}")])

    await status.delete()
    await message.reply_text(f"**Search Result For...**\n`{text}`\n\n👇 Story chunein:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^sel_"))
async def handle_story_click(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass

    story_id = callback_query.data.split("_")[1]
    story = STORY_STORE.get(story_id) or get_story_by_id_or_slug(story_id)
    if not story:
        return

    title = story.get("title", "Story")
    category = story.get("category", "Hindi")
    cover_image = story.get("coverImage")
    episodes = story.get("episodes", [])

    if not episodes:
        try:
            r = session.get(f"https://www.namanstorybook.in/api/series/{story_id}", timeout=10)
            if r.status_code == 200:
                episodes = r.json().get("episodes", [])
        except Exception:
            pass

    USER_STATE[callback_query.from_user.id] = {
        "title": title,
        "episodes": episodes,
        "cover": cover_image
    }

    caption = (
        f"📖 **{title}**\n\n"
        f"🗣️ **Language:** {category}\n"
        f"📊 **Total Episodes:** {len(episodes)}\n\n"
        f"📌 **Send episode number or range to start download.**\n"
        f"• *Examples: 5 or 1-10*"
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("All Episodes", callback_data=f"all_{story_id}"),
            InlineKeyboardButton("Select Episodes", callback_data=f"page_1_{story_id}")
        ],
        [
            InlineKeyboardButton("🔔 Auto-Set New Episodes", callback_data=f"auto_{story_id}")
        ]
    ])

    if cover_image:
        await callback_query.message.reply_photo(photo=cover_image, caption=caption, reply_markup=buttons)
    else:
        await callback_query.message.reply_text(text=caption, reply_markup=buttons)

@app.on_callback_query(filters.regex(r"^auto_"))
async def handle_auto_button(client, callback_query):
    story_id = callback_query.data.split("_")[1]
    story = STORY_STORE.get(story_id) or get_story_by_id_or_slug(story_id)
    if not story:
        await callback_query.answer("Story load nahi hui!", show_alert=True)
        return

    episodes = story.get("episodes", [])
    tracker = load_tracker()
    tracker[story_id] = {
        "title": story.get("title"),
        "chat_id": callback_query.message.chat.id,
        "last_count": len(episodes)
    }
    save_tracker(tracker)
    await callback_query.answer("✅ Auto-Set Activated!", show_alert=True)
    await callback_query.message.reply_text(
        f"🔔 **{story.get('title')}** ko Auto-Download par set kar diya gaya hai (Current: {len(episodes)} Eps).\nJab bhi naya episode aayega, bot khud bhej dega!"
    )

@app.on_callback_query(filters.regex(r"^all_"))
async def handle_all_episodes(client, callback_query):
    try:
        await callback_query.answer("All Episodes Download shuru...")
    except Exception:
        pass
    story_id = callback_query.data.split("_")[1]
    story = STORY_STORE.get(story_id) or get_story_by_id_or_slug(story_id)
    if not story:
        return
    episodes = story.get("episodes", [])
    for idx, ep in enumerate(episodes, 1):
        ep_id = ep.get("id") if isinstance(ep, dict) else str(ep)
        await process_and_send_episode(callback_query.message.chat.id, ep_id, idx, story.get("title"), story.get("coverImage"))

@app.on_callback_query(filters.regex(r"^page_"))
async def handle_select_episodes_grid(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass
    parts = callback_query.data.split("_")
    page = int(parts[1])
    story_id = parts[2]
    story = STORY_STORE.get(story_id) or get_story_by_id_or_slug(story_id)
    episodes = story.get("episodes", [])

    per_page = 20
    total_pages = (len(episodes) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    current_eps = episodes[start:end]

    buttons, row = [], []
    for idx, ep in enumerate(current_eps, start=start + 1):
        ep_id = ep.get("id") if isinstance(ep, dict) else str(ep)
        row.append(InlineKeyboardButton(f"Ep {idx}", callback_data=f"one_{ep_id}_{idx}_{story_id}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}_{story_id}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}_{story_id}"))
    if nav:
        buttons.append(nav)

    await callback_query.message.reply_text(f"🔢 Episodes Page {page}/{total_pages}:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^one_"))
async def handle_single_episode(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass
    parts = callback_query.data.split("_")
    ep_id, ep_num, story_id = parts[1], parts[2], parts[3]
    story = STORY_STORE.get(story_id) or get_story_by_id_or_slug(story_id)
    await process_and_send_episode(callback_query.message.chat.id, ep_id, int(ep_num), story.get("title"), story.get("coverImage"))

login_to_site()
print(">>> Naman Story Bot v2 is 100% READY!")
app.run()
