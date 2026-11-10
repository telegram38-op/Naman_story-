import os
import re
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

def get_full_story_details(identifier):
    """Story aur uske episodes ka pura detail (title, image, ep number) nikalna"""
    story_obj = None
    stories = fetch_all_stories()
    for s in stories:
        if s.get("id") == identifier or s.get("slug") == identifier:
            story_obj = s
            break

    # Detailed series API call taaki har episode ka title aur image mil sake
    slug_or_id = story_obj.get("slug") if story_obj and story_obj.get("slug") else identifier
    for target in [identifier, slug_or_id]:
        try:
            r = session.get(f"https://www.namanstorybook.in/api/series/{target}", timeout=10)
            if r.status_code == 200:
                detail = r.json()
                if isinstance(detail, dict) and detail.get("episodes"):
                    return detail
        except Exception:
            pass

    return story_obj

def extract_episode_meta(ep, idx, fallback_cover=None):
    """Website ke episode object se exact Title, Episode Number aur uski apni Photo nikalna"""
    if not isinstance(ep, dict):
        return str(ep), f"Ep {idx}", f"Episode {idx}", fallback_cover

    ep_id = ep.get("id", "")
    
    # Website par jo asli title hai (e.g. "1002-1003. DR DHRUV")
    raw_title = ep.get("title") or ep.get("name") or ""
    
    # Website par jo asli episode number hai (e.g. "1002-1003" ya "E1002-1003")
    raw_ep_num = (
        ep.get("episodeNumber") 
        or ep.get("episode_number") 
        or ep.get("number") 
        or ep.get("epNumber")
        or ""
    )

    # Agar episode number title ke andar hi likha hai (jaise "1002-1003. DR DHRUV")
    if not raw_ep_num and raw_title:
        m = re.match(r'^([E0-9]+(?:\s*-\s*[0-9]+)?)', raw_title.strip(), re.I)
        if m:
            raw_ep_num = m.group(1)

    # Button ke liye short label
    if raw_ep_num:
        clean_num = str(raw_ep_num).lstrip("Ee")
        btn_label = f"E{clean_num}"
    elif raw_title:
        btn_label = raw_title[:18]
    else:
        btn_label = f"Ep {idx}"

    # Full display title (Audio aur Photo caption ke liye)
    if raw_title:
        full_title = raw_title
        if raw_ep_num and str(raw_ep_num) not in raw_title:
            full_title = f"{raw_ep_num}. {raw_title}"
    elif raw_ep_num:
        full_title = f"Episode {raw_ep_num}"
    else:
        full_title = f"Episode {idx}"

    # Episode ki apni specific photo dhoondhna (Story cover se pehle)
    ep_image = (
        ep.get("coverImage")
        or ep.get("thumbnail")
        or ep.get("image")
        or ep.get("imageUrl")
        or ep.get("poster")
        or ep.get("thumb")
        or fallback_cover
    )

    return ep_id, btn_label, full_title, ep_image

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

async def process_and_send_episode(chat_id, ep_obj, idx, story_title, story_cover=None):
    ep_id, btn_label, full_ep_title, ep_image_url = extract_episode_meta(ep_obj, idx, story_cover)

    status = await app.send_message(chat_id, f"⏳ **{full_ep_title}** fetch ho raha hai...")
    audio_url = get_audio_url(ep_id)
    if not audio_url:
        await safe_edit(status, f"❌ **{full_ep_title}** ka audio link nahi mila.")
        return

    # Safe filename banana
    safe_name = re.sub(r'[\\/*?:"<>|]', "", full_ep_title).strip().replace(" ", "_")
    raw_file = f"temp_{ep_id}.mp3"
    m4a_file = f"{safe_name}.m4a"
    thumb_file = f"thumb_{ep_id}.jpg"

    try:
        await safe_edit(status, f"⬇️ Downloading **{full_ep_title}**...")
        download_file(audio_url, raw_file)

        await safe_edit(status, f"⚡ M4A 64k compression...")
        final_file = convert_to_m4a_compressed(raw_file, m4a_file)

        duration_sec = get_audio_duration_seconds(final_file)
        mins, secs = divmod(duration_sec, 60)
        duration_text = f"{mins:02d}:{secs:02d}"
        size_mb = os.path.getsize(final_file) / (1024 * 1024)

        # Episode ki apni photo download karke pehle bhejna
        if ep_image_url:
            try:
                download_file(ep_image_url, thumb_file)
                await app.send_photo(
                    chat_id=chat_id,
                    photo=thumb_file,
                    caption=(
                        f"🎬 **{full_ep_title}**\n"
                        f"📖 **Series:** {story_title}\n"
                        f"🏷️ **Episode:** `{btn_label}`"
                    )
                )
            except Exception as e:
                print("Ep image error:", e)

        await safe_edit(status, f"⬆️ Uploading **{full_ep_title}**...")
        await app.send_audio(
            chat_id=chat_id,
            audio=final_file,
            title=full_ep_title,
            performer=story_title,
            duration=duration_sec,
            thumb=thumb_file if os.path.exists(thumb_file) else None,
            caption=(
                f"🎵 **{full_ep_title}**\n"
                f"📖 **Story:** {story_title}\n"
                f"⏱ **Duration:** `{duration_text}`\n"
                f"📦 **Size:** `{size_mb:.2f} MB`"
            )
        )
        await status.delete()

    except Exception as e:
        await safe_edit(status, f"⚠️ Error ({full_ep_title}): {e}")
    finally:
        for f in [raw_file, m4a_file, thumb_file]:
            if os.path.exists(f):
                os.remove(f)

async def background_auto_tracker():
    while True:
        await asyncio.sleep(600)
        try:
            tracker = load_tracker()
            for s_id, data in tracker.items():
                chat_id = data.get("chat_id")
                known_ids = set(data.get("known_ep_ids", []))
                story = get_full_story_details(s_id)
                if not story:
                    continue

                episodes = story.get("episodes", [])
                new_found = False

                for idx, ep in enumerate(episodes, start=1):
                    ep_id = ep.get("id") if isinstance(ep, dict) else str(ep)
                    if ep_id not in known_ids:
                        _, _, full_title, _ = extract_episode_meta(ep, idx, story.get("coverImage"))
                        await app.send_message(
                            chat_id,
                            f"🔔 **New Episode Released!**\n📖 **{story.get('title')}**\n🎬 `{full_title}`"
                        )
                        await process_and_send_episode(chat_id, ep, idx, story.get("title"), story.get("coverImage"))
                        known_ids.add(ep_id)
                        new_found = True

                if new_found:
                    data["known_ep_ids"] = list(known_ids)
                    data["last_count"] = len(episodes)
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
    story = get_full_story_details(query)
    if not story:
        await message.reply_text("❌ Story nahi mili. Sahi slug ya ID daalein.")
        return

    s_id = story.get("id") or query
    episodes = story.get("episodes", [])
    ep_ids = [ep.get("id") if isinstance(ep, dict) else str(ep) for ep in episodes]
    
    tracker = load_tracker()
    tracker[s_id] = {
        "title": story.get("title"),
        "chat_id": message.chat.id,
        "last_count": len(episodes),
        "known_ep_ids": ep_ids
    }
    save_tracker(tracker)

    await message.reply_text(
        f"✅ **Auto-Set Activated!**\n\n"
        f"📖 **Story:** {story.get('title')}\n"
        f"🔢 **Current Episodes:** {len(episodes)}\n\n"
        f"Jab bhi naya episode aayega, bot uski original photo aur title ke sath yahan bhej dega."
    )

@app.on_message(filters.command("tracker"))
async def tracker_cmd(client, message):
    tracker = load_tracker()
    if not tracker:
        await message.reply_text("Koi bhi story auto-set par nahi hai.")
        return
    text = "📋 **Active Auto-Trackers:**\n\n"
    for s_id, d in tracker.items():
        text += f"• **{d.get('title')}** (Tracked: {d.get('last_count')} Eps)\n"
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

        selected_eps = []
        # 1. Check agar user ne serial range di hai (jaise 1-5)
        if "-" in text and all(p.strip().isdigit() for p in text.split("-", 1)):
            s_no, e_no = map(int, text.split("-", 1))
            if 1 <= s_no <= len(episodes) and e_no <= len(episodes):
                for idx in range(s_no, e_no + 1):
                    selected_eps.append((idx, episodes[idx - 1]))
            else:
                # Check agar website ka episode নাম্বার hai (jaise 1002-1003)
                for idx, ep in enumerate(episodes, 1):
                    _, btn_l, full_t, _ = extract_episode_meta(ep, idx)
                    if text.lower() in full_t.lower() or text.lower() in btn_l.lower():
                        selected_eps.append((idx, ep))

        elif text.isdigit():
            val = int(text)
            if 1 <= val <= len(episodes):
                selected_eps.append((val, episodes[val - 1]))
            else:
                for idx, ep in enumerate(episodes, 1):
                    _, btn_l, full_t, _ = extract_episode_meta(ep, idx)
                    if text in full_t or text in btn_l:
                        selected_eps.append((idx, ep))

        if selected_eps:
            for idx, ep_data in selected_eps:
                await process_and_send_episode(message.chat.id, ep_data, idx, story_title, cover_image)
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
    story = get_full_story_details(story_id) or STORY_STORE.get(story_id)
    if not story:
        return

    STORY_STORE[story_id] = story
    title = story.get("title", "Story")
    category = story.get("category", "Hindi")
    cover_image = story.get("coverImage")
    episodes = story.get("episodes", [])

    USER_STATE[callback_query.from_user.id] = {
        "title": title,
        "episodes": episodes,
        "cover": cover_image
    }

    caption = (
        f"📖 **{title}**\n\n"
        f"🗣️ **Language:** {category}\n"
        f"📊 **Total Available Episodes:** {len(episodes)}\n\n"
        f"📌 **Send episode number or range to start download.**\n"
        f"• *Examples: 1 or 1-5 or 1002-1003*"
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
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    if not story:
        await callback_query.answer("Story load nahi hui!", show_alert=True)
        return

    episodes = story.get("episodes", [])
    ep_ids = [ep.get("id") if isinstance(ep, dict) else str(ep) for ep in episodes]
    tracker = load_tracker()
    tracker[story_id] = {
        "title": story.get("title"),
        "chat_id": callback_query.message.chat.id,
        "last_count": len(episodes),
        "known_ep_ids": ep_ids
    }
    save_tracker(tracker)
    await callback_query.answer("✅ Auto-Set Activated!", show_alert=True)
    await callback_query.message.reply_text(
        f"🔔 **{story.get('title')}** ko Auto-Download par set kar diya gaya hai (Current: {len(episodes)} Eps).\nJab bhi naya episode aayega, bot uski photo aur title ke sath bhej dega!"
    )

@app.on_callback_query(filters.regex(r"^all_"))
async def handle_all_episodes(client, callback_query):
    try:
        await callback_query.answer("All Episodes Download shuru...")
    except Exception:
        pass
    story_id = callback_query.data.split("_")[1]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    if not story:
        return
    episodes = story.get("episodes", [])
    for idx, ep in enumerate(episodes, 1):
        await process_and_send_episode(callback_query.message.chat.id, ep, idx, story.get("title"), story.get("coverImage"))

@app.on_callback_query(filters.regex(r"^page_"))
async def handle_select_episodes_grid(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass
    parts = callback_query.data.split("_")
    page = int(parts[1])
    story_id = parts[2]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    episodes = story.get("episodes", [])

    per_page = 10
    total_pages = (len(episodes) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    current_eps = episodes[start:end]

    buttons = []
    for idx, ep in enumerate(current_eps, start=start + 1):
        ep_id, btn_label, full_title, _ = extract_episode_meta(ep, idx)
        # Button par exact Episode Number + Title dikhana (jaise: "1002-1003. DR DHRUV")
        buttons.append([InlineKeyboardButton(f"▶️ {full_title}", callback_data=f"one_{idx}_{story_id}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}_{story_id}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}_{story_id}"))
    if nav:
        buttons.append(nav)

    await callback_query.message.reply_text(
        f"🎬 **{story.get('title')} - Episodes List (Page {page}/{total_pages}):**\n👇 Jis episode ko download karna hai us par click karein:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^one_"))
async def handle_single_episode(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass
    parts = callback_query.data.split("_")
    idx = int(parts[1])
    story_id = parts[2]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    episodes = story.get("episodes", [])
    if 1 <= idx <= len(episodes):
        ep_obj = episodes[idx - 1]
        await process_and_send_episode(callback_query.message.chat.id, ep_obj, idx, story.get("title"), story.get("coverImage"))

login_to_site()
print(">>> Naman Story Bot v3 (Episode Photos + Exact Titles) is READY!")
app.run()
