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

BASE_URL = "https://www.namanstorybook.in"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/",
    "Accept": "application/json, text/plain, */*"
})

app = Client("naman_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

STORY_STORE = {}
EPISODE_STORE = {}
USER_STATE = {}
CANCEL_FLAGS = {}
TRACKER_FILE = "autoset_data.json"
TRACKER_RUNNING = False

def log(msg):
    print(msg, flush=True)

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

def normalize_url(u):
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return f"{BASE_URL}{u}"
    return None

def find_image_in_dict(d, ignore_url=None):
    if not isinstance(d, dict):
        return None

    priority_keys = [
        "thumbnail", "thumbnailUrl", "thumb", "thumbUrl",
        "episodeImage", "episode_image", "epImage", "episodeThumbnail",
        "image", "imageUrl", "img", "imgUrl",
        "coverImage", "cover_image", "cover", "coverUrl",
        "banner", "bannerUrl", "poster", "posterUrl", "artwork", "photo"
    ]
    for k in priority_keys:
        val = d.get(k)
        if isinstance(val, str) and val.strip():
            full = normalize_url(val)
            if full and full != ignore_url:
                return full
        elif isinstance(val, dict):
            nested = val.get("url") or val.get("src") or val.get("path")
            full = normalize_url(nested)
            if full and full != ignore_url:
                return full

    for k, val in d.items():
        if k in ["audioUrl", "audio_url", "url", "id", "seriesId", "storyId"]:
            continue
        if isinstance(val, str):
            low = val.lower()
            if any(ext in low for ext in [".jpg", ".jpeg", ".png", ".webp", "r2.dev", "cloudfront", "images", "uploads"]):
                full = normalize_url(val)
                if full and full != ignore_url:
                    return full
    return None

def login_to_site():
    """Exact working login without corrupting session cookies"""
    session.cookies.clear()
    session.headers.pop("Authorization", None)
    login_urls = [f"{BASE_URL}/api/auth/login", f"{BASE_URL}/api/login"]
    payload = {"email": EMAIL, "password": PASSWORD}
    for url in login_urls:
        try:
            res = session.post(url, json=payload, timeout=12)
            log(f"[LOGIN] {url} -> Status: {res.status_code}")
            if res.status_code in [200, 201]:
                # Agar server ne Set-Cookie nahi bheja aur JSON me token diya hai tabhi header lagayein
                if not session.cookies.get("access_token"):
                    try:
                        data = res.json()
                        if isinstance(data, dict):
                            acc = data.get("accessToken") or data.get("access_token") or data.get("token")
                            if acc:
                                session.headers["Authorization"] = f"Bearer {acc}"
                    except Exception:
                        pass
                return True
        except Exception as e:
            log(f"[LOGIN ERR]: {e}")
    return False

def fetch_all_stories():
    try:
        res = session.get(f"{BASE_URL}/api/stories", timeout=12)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else data.get("stories", [])
    except Exception:
        pass
    return []

def get_full_story_details(identifier):
    story_obj = None
    stories = fetch_all_stories()
    for s in stories:
        if str(s.get("id")) == str(identifier) or str(s.get("slug")) == str(identifier):
            story_obj = s
            break

    slug = story_obj.get("slug") if story_obj and story_obj.get("slug") else identifier
    s_id = story_obj.get("id") if story_obj and story_obj.get("id") else identifier

    endpoints = [
        f"{BASE_URL}/api/series/{s_id}",
        f"{BASE_URL}/api/series/{slug}",
        f"{BASE_URL}/api/stories/{s_id}",
        f"{BASE_URL}/api/stories/{slug}"
    ]
    for ep_url in endpoints:
        try:
            r = session.get(ep_url, timeout=10)
            if r.status_code == 200:
                detail = r.json()
                if isinstance(detail, dict):
                    inner = detail.get("series") or detail.get("story") or detail.get("data") or detail
                    if isinstance(inner, dict) and inner.get("episodes"):
                        # Agar fetch_all_stories wale ep object me zyada keys hain toh merge karein
                        return inner
        except Exception:
            pass

    return story_obj

def extract_episode_meta(ep, idx, fallback_cover=None):
    fallback_cover = normalize_url(fallback_cover)
    if not isinstance(ep, dict):
        return str(ep), f"Ep {idx}", f"Episode {idx}", fallback_cover

    ep_id = str(ep.get("id") or ep.get("_id") or "")
    raw_title = ep.get("title") or ep.get("name") or ""
    raw_ep_num = (
        ep.get("episodeNumber")
        or ep.get("episode_number")
        or ep.get("number")
        or ep.get("epNumber")
        or ""
    )

    if not raw_ep_num and raw_title:
        m = re.match(r'^([E0-9]+(?:\s*-\s*[0-9]+)?)', raw_title.strip(), re.I)
        if m:
            raw_ep_num = m.group(1)

    if raw_ep_num:
        clean_num = str(raw_ep_num).lstrip("Ee")
        btn_label = f"E{clean_num}"
    elif raw_title:
        btn_label = raw_title[:18]
    else:
        btn_label = f"Ep {idx}"

    if raw_title:
        full_title = raw_title
        if raw_ep_num and str(raw_ep_num) not in raw_title:
            full_title = f"{raw_ep_num}. {raw_title}"
    elif raw_ep_num:
        full_title = f"Episode {raw_ep_num}"
    else:
        full_title = f"Episode {idx}"

    ep_image = find_image_in_dict(ep, ignore_url=fallback_cover)
    if not ep_image:
        ep_image = find_image_in_dict(ep) or fallback_cover

    return ep_id, btn_label, full_title, ep_image

def get_audio_url_and_meta(ep_id, ep_obj=None, story_cover=None):
    """Exact working /api/episodes/{id}/audio-url with debug info"""
    debug_notes = []

    # 1. Check agar ep_obj me pehle se direct audio link hai
    if isinstance(ep_obj, dict):
        for k in ["audioUrl", "audio_url", "audio", "fileUrl", "streamUrl", "mp3Url"]:
            val = ep_obj.get(k)
            if isinstance(val, str) and val.strip().startswith("http"):
                return val.strip(), find_image_in_dict(ep_obj, ignore_url=story_cover), "from_ep_obj"

    # 2. Main audio-url API call
    api_url = f"{BASE_URL}/api/episodes/{ep_id}/audio-url"
    try:
        res = session.get(api_url, timeout=15)
        log(f"[AUDIO API 1st] {res.status_code} -> {res.text[:200]}")
        debug_notes.append(f"Try1({res.status_code}): {res.text[:80]}")

        if res.status_code != 200:
            log(">>> Re-logging in to site...")
            login_to_site()
            res = session.get(api_url, timeout=15)
            log(f"[AUDIO API 2nd] {res.status_code} -> {res.text[:200]}")
            debug_notes.append(f"Try2({res.status_code}): {res.text[:80]}")

        if res.status_code == 200:
            try:
                d = res.json()
                if isinstance(d, dict):
                    inner = d.get("data") or d.get("episode") or d
                    audio_u = (
                        d.get("audioUrl") or d.get("url") or d.get("audio_url") or d.get("signedUrl") or d.get("link")
                        or (inner.get("audioUrl") if isinstance(inner, dict) else None)
                        or (inner.get("url") if isinstance(inner, dict) else None)
                    )
                    extra_img = find_image_in_dict(inner if isinstance(inner, dict) else d, ignore_url=story_cover)
                    if audio_u:
                        return normalize_url(audio_u), extra_img, "ok"
                    else:
                        debug_notes.append(f"Keys: {list(d.keys())}")
                elif isinstance(d, str) and d.startswith("http"):
                    return d.strip(), None, "ok"
            except Exception:
                txt = res.text.strip().strip('"')
                if txt.startswith("http"):
                    return txt, None, "ok"
    except Exception as e:
        debug_notes.append(f"Err: {e}")

    return None, None, " | ".join(debug_notes)

def download_file(url, out_path):
    # Cloudflare R2 signed URLs par session cookies nahi bhejni chahiye, isliye plain requests.get
    headers = {"User-Agent": "Mozilla/5.0"}
    with requests.get(url, headers=headers, stream=True, timeout=90) as r:
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

    status = await app.send_message(chat_id, f"⏳ **{full_ep_title}** fetch ho raha hai...\n*(Rokne ke liye /cancel bhejein)*")
    audio_url, extra_img, debug_info = get_audio_url_and_meta(ep_id, ep_obj, story_cover)

    if extra_img:
        ep_image_url = extra_img

    if not audio_url:
        ep_keys = list(ep_obj.keys()) if isinstance(ep_obj, dict) else "str"
        await safe_edit(
            status,
            f"❌ **{full_ep_title}** ka audio link nahi mila.\n"
            f"🆔 `ID: {ep_id}`\n"
            f"📡 `API: {debug_info}`\n"
            f"🔑 `EpKeys: {ep_keys}`"
        )
        return

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
                log(f"Ep image error: {e}")

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
            for s_id, data in list(tracker.items()):
                chat_id = data.get("chat_id")
                known_ids = set(data.get("known_ep_ids", []))
                story = get_full_story_details(s_id)
                if not story:
                    continue

                episodes = story.get("episodes", [])
                new_found = False

                for idx, ep in enumerate(episodes, start=1):
                    ep_id = str(ep.get("id") if isinstance(ep, dict) else ep)
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
            log(f"Tracker error: {e}")

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    await message.reply_text(
        "🎧 **Naman Story Book Bot**\n\n"
        "• Story search karne ke liye naam bhejein (e.g. `demon`).\n"
        "• Chal rahe download ko rokne ke liye: `/cancel` ya `/stop`\n"
        "• Auto-Set list aur band karne ke liye: `/tracker`\n"
        "• Saare Auto-Set ek sath hatane ke liye: `/stopauto`"
    )

@app.on_message(filters.command(["cancel", "stop"]))
async def cancel_cmd(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    CANCEL_FLAGS[chat_id] = True
    USER_STATE.pop(user_id, None)
    await message.reply_text("🛑 **Stopped!** Chal raha batch download aur active selection cancel kar diya gaya hai.")

@app.on_message(filters.command(["stopauto", "untrack"]))
async def stop_auto_cmd(client, message):
    args = message.text.split(maxsplit=1)
    tracker = load_tracker()
    if not tracker:
        await message.reply_text("ℹ️ Koi bhi story Auto-Set par nahi hai.")
        return

    if len(args) == 1:
        save_tracker({})
        await message.reply_text("🛑 **Saare Auto-Set trackers band kar diye gaye hain!**")
        return

    query = args[1].strip().lower()
    removed = []
    for s_id in list(tracker.keys()):
        title = tracker[s_id].get("title", "").lower()
        if query in s_id.lower() or query in title:
            removed.append(tracker[s_id].get("title", s_id))
            del tracker[s_id]

    save_tracker(tracker)
    if removed:
        await message.reply_text(f"🛑 Auto-Set hataya gaya: **{', '.join(removed)}**")
    else:
        await message.reply_text("❌ Is naam ki koi story Auto-Set me nahi mili. `/tracker` dekhein.")

@app.on_message(filters.command("autoset"))
async def autoset_cmd(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: `/autoset <story_name ya slug>`\nBand karne ke liye: `/tracker` ya `/stopauto`")
        return

    query = args[1].strip()
    story = get_full_story_details(query)
    if not story:
        await message.reply_text("❌ Story nahi mili. Sahi slug ya ID daalein.")
        return

    s_id = str(story.get("id") or query)
    episodes = story.get("episodes", [])
    ep_ids = [str(ep.get("id") if isinstance(ep, dict) else ep) for ep in episodes]
    
    tracker = load_tracker()
    tracker[s_id] = {
        "title": story.get("title"),
        "chat_id": message.chat.id,
        "last_count": len(episodes),
        "known_ep_ids": ep_ids
    }
    save_tracker(tracker)

    btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Stop Auto-Set", callback_data=f"unauto_{s_id}")]])
    await message.reply_text(
        f"✅ **Auto-Set Activated!**\n\n"
        f"📖 **Story:** {story.get('title')}\n"
        f"🔢 **Current Episodes:** {len(episodes)}",
        reply_markup=btn
    )

@app.on_message(filters.command("tracker"))
async def tracker_cmd(client, message):
    tracker = load_tracker()
    if not tracker:
        await message.reply_text("ℹ️ Koi bhi story Auto-Set par nahi hai.")
        return

    text = "📋 **Active Auto-Trackers:**\n*(Band karne ke liye neeche button dabayein)*\n\n"
    buttons = []
    for s_id, d in tracker.items():
        title = d.get("title", s_id)
        text += f"• **{title}** ({d.get('last_count')} Eps)\n"
        buttons.append([InlineKeyboardButton(f"❌ Stop: {title}", callback_data=f"unauto_{s_id}")])

    buttons.append([InlineKeyboardButton("🗑️ Stop All Auto-Sets", callback_data="unauto_ALL")])
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex(r"^unauto_"))
async def handle_unauto_callback(client, callback_query):
    target = callback_query.data.split("_", 1)[1]
    tracker = load_tracker()

    if target == "ALL":
        save_tracker({})
        await callback_query.answer("Saare Auto-Set band kar diye gaye!", show_alert=True)
        await safe_edit(callback_query.message, "🛑 **Saare Auto-Set trackers band kar diye gaye hain.**")
        return

    if target in tracker:
        title = tracker[target].get("title", target)
        del tracker[target]
        save_tracker(tracker)
        await callback_query.answer(f"Stopped: {title}", show_alert=True)
        await safe_edit(callback_query.message, f"🛑 **{title}** ka Auto-Set band kar diya gaya hai.")
    else:
        await callback_query.answer("Yeh pehle hi band ho chuka hai.", show_alert=True)

@app.on_message(filters.text & ~filters.command(["start", "autoset", "tracker", "cancel", "stop", "stopauto", "untrack"]))
async def handle_search_or_range(client, message):
    global TRACKER_RUNNING
    if not TRACKER_RUNNING:
        TRACKER_RUNNING = True
        asyncio.create_task(background_auto_tracker())

    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    if user_id in USER_STATE:
        state = USER_STATE[user_id]
        episodes = state["episodes"]
        story_title = state["title"]
        cover_image = state["cover"]

        selected_eps = []
        if "-" in text and all(p.strip().isdigit() for p in text.split("-", 1)):
            s_no, e_no = map(int, text.split("-", 1))
            if 1 <= s_no <= len(episodes) and e_no <= len(episodes):
                for idx in range(s_no, e_no + 1):
                    selected_eps.append((idx, episodes[idx - 1]))
            else:
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
            CANCEL_FLAGS[chat_id] = False
            for idx, ep_data in selected_eps:
                if CANCEL_FLAGS.get(chat_id):
                    await message.reply_text("🛑 **Download Cancelled!**")
                    break
                await process_and_send_episode(chat_id, ep_data, idx, story_title, cover_image)
            return

    status = await message.reply_text("🔍 Search kiya ja raha hai...")
    all_stories = fetch_all_stories()
    matches = [s for s in all_stories if text.lower() in s.get("title", "").lower() or text.lower() in s.get("slug", "").lower()]

    if not matches:
        await safe_edit(status, f"❌ '{text}' naam ki story nahi mili.")
        return

    buttons = []
    for s in matches[:10]:
        s_id = str(s.get("id"))
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

    story_id = callback_query.data.split("_", 1)[1]
    story = get_full_story_details(story_id) or STORY_STORE.get(story_id)
    if not story:
        return

    STORY_STORE[story_id] = story
    title = story.get("title", "Story")
    category = story.get("category", "Hindi")
    cover_image = story.get("coverImage")
    episodes = story.get("episodes", [])

    for idx, ep in enumerate(episodes, 1):
        if isinstance(ep, dict) and ep.get("id"):
            EPISODE_STORE[str(ep.get("id"))] = {
                "ep": ep,
                "idx": idx,
                "story_title": title,
                "cover": cover_image
            }

    USER_STATE[callback_query.from_user.id] = {
        "title": title,
        "episodes": episodes,
        "cover": cover_image
    }

    tracker = load_tracker()
    is_tracked = story_id in tracker

    caption = (
        f"📖 **{title}**\n\n"
        f"🗣️ **Language:** {category}\n"
        f"📊 **Total Available Episodes:** {len(episodes)}\n\n"
        f"📌 **Send episode number or range to start download.**\n"
        f"• *Examples: 1 or 1-5 or 1002*\n"
        f"• *Send `/cancel` anytime to stop*"
    )

    auto_btn = (
        InlineKeyboardButton("❌ Stop Auto-Set", callback_data=f"unauto_{story_id}")
        if is_tracked else
        InlineKeyboardButton("🔔 Auto-Set New Episodes", callback_data=f"auto_{story_id}")
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("All Episodes", callback_data=f"all_{story_id}"),
            InlineKeyboardButton("Select Episodes", callback_data=f"page_1_{story_id}")
        ],
        [auto_btn]
    ])

    if cover_image:
        await callback_query.message.reply_photo(photo=cover_image, caption=caption, reply_markup=buttons)
    else:
        await callback_query.message.reply_text(text=caption, reply_markup=buttons)

@app.on_callback_query(filters.regex(r"^auto_"))
async def handle_auto_button(client, callback_query):
    story_id = callback_query.data.split("_", 1)[1]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    if not story:
        await callback_query.answer("Story load nahi hui!", show_alert=True)
        return

    episodes = story.get("episodes", [])
    ep_ids = [str(ep.get("id") if isinstance(ep, dict) else ep) for ep in episodes]
    tracker = load_tracker()
    tracker[story_id] = {
        "title": story.get("title"),
        "chat_id": callback_query.message.chat.id,
        "last_count": len(episodes),
        "known_ep_ids": ep_ids
    }
    save_tracker(tracker)
    await callback_query.answer("✅ Auto-Set Activated!", show_alert=True)

    stop_btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Stop Auto-Set", callback_data=f"unauto_{story_id}")]])
    await callback_query.message.reply_text(
        f"🔔 **{story.get('title')}** ko Auto-Download par set kar diya gaya hai (Current: {len(episodes)} Eps).\n"
        f"Jab bhi naya episode aayega, bot khud bhej dega!",
        reply_markup=stop_btn
    )

@app.on_callback_query(filters.regex(r"^all_"))
async def handle_all_episodes(client, callback_query):
    try:
        await callback_query.answer("All Episodes Download shuru...")
    except Exception:
        pass
    chat_id = callback_query.message.chat.id
    CANCEL_FLAGS[chat_id] = False

    story_id = callback_query.data.split("_", 1)[1]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    if not story:
        return
    episodes = story.get("episodes", [])
    for idx, ep in enumerate(episodes, 1):
        if CANCEL_FLAGS.get(chat_id):
            await app.send_message(chat_id, "🛑 **All Episodes Download Cancelled!**")
            break
        await process_and_send_episode(chat_id, ep, idx, story.get("title"), story.get("coverImage"))

@app.on_callback_query(filters.regex(r"^page_"))
async def handle_select_episodes_grid(client, callback_query):
    try:
        await callback_query.answer()
    except Exception:
        pass
    parts = callback_query.data.split("_", 2)
    page = int(parts[1])
    story_id = parts[2]
    story = STORY_STORE.get(story_id) or get_full_story_details(story_id)
    if not story:
        return
    episodes = story.get("episodes", [])
    title = story.get("title", "Story")
    cover_image = story.get("coverImage")

    per_page = 10
    total_pages = (len(episodes) + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    current_eps = episodes[start:end]

    buttons = []
    for idx, ep in enumerate(current_eps, start=start + 1):
        ep_id, _, full_title, _ = extract_episode_meta(ep, idx)
        EPISODE_STORE[str(ep_id)] = {
            "ep": ep,
            "idx": idx,
            "story_title": title,
            "cover": cover_image
        }
        buttons.append([InlineKeyboardButton(f"▶️ {full_title}", callback_data=f"epdl_{ep_id}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}_{story_id}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}_{story_id}"))
    if nav:
        buttons.append(nav)

    await callback_query.message.reply_text(
        f"🎬 **{title} - Episodes List (Page {page}/{total_pages}):**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^epdl_"))
async def handle_single_episode(client, callback_query):
    try:
        await callback_query.answer("Downloading episode...")
    except Exception:
        pass
    ep_id = callback_query.data.split("_", 1)[1]
    cached = EPISODE_STORE.get(str(ep_id))
    if cached:
        await process_and_send_episode(
            callback_query.message.chat.id,
            cached["ep"],
            cached["idx"],
            cached["story_title"],
            cached["cover"]
        )
    else:
        await process_and_send_episode(
            callback_query.message.chat.id,
            {"id": ep_id, "title": f"Episode {ep_id}"},
            1,
            "Naman Story",
            None
        )

login_to_site()
log(">>> Naman Story Bot v6 (Clean Cookie Login + Live Telegram Debug) is READY!")
app.run()
