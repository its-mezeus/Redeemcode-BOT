# bot_with_termux_status_and_styled_ping.py
import os
import random
import string
import logging
import time
from threading import Thread
from typing import Set, Dict, Any, List

from flask import Flask, render_template_string, jsonify, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.error import Forbidden, BadRequest
from telegram.constants import ParseMode  # For HTML parse mode

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
# FORCE_JOIN_CHANNEL is now an optional starting list of channels (comma-separated)
FORCE_JOIN_CHANNEL_ENV = os.getenv("FORCE_JOIN_CHANNEL", "")
WEB_SECRET = os.getenv("WEB_SECRET", "")  # secret token for protected HTTP endpoints (restart/open)
BOT_VERSION = os.getenv("BOT_VERSION", "v1.0")

if not BOT_TOKEN or not ADMIN_IDS:
    # Relaxed check: FORCE_JOIN_CHANNEL is now optional
    raise ValueError("Missing BOT_TOKEN or ADMIN_IDS environment variables!")

# ---------- Logging ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Runtime state ----------
codes: Dict[str, Dict[str, Any]] = {}  # in-memory codes store
_start_time = time.time()
# pending screenshot requests: maps user_id -> {"code": code, "creator_id": id, "requested_at": timestamp}
pending_screenshots: Dict[int, Dict[str, Any]] = {}

# New global state for multiple force join channels (using a Set for uniqueness and O(1) checks)
# Initialize from environment variable
FORCE_CHANNELS: Set[str] = set(
    f"@{x.lstrip('@')}"
    for x in FORCE_JOIN_CHANNEL_ENV.split(",")
    if x.strip()
)

# ---------- Helpers ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def generate_random_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def format_uptime(seconds: float) -> str:
    s = int(seconds)
    hours = s // 3600
    mins = (s % 3600) // 60
    secs = s % 60
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"

def compute_active_users() -> int:
    users: Set[int] = set()
    for info in codes.values():
        used_by = info.get("used_by")
        if isinstance(used_by, list):
            users.update(used_by)
        elif isinstance(used_by, int):
            users.add(used_by)
    return len(users)

# ---------- Force Join Check (async) - Updated for multiple channels ----------
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not FORCE_CHANNELS:
        return True # No channels required
    
    user_id = update.effective_user.id
    missing_channels: List[str] = []

    for channel in FORCE_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing_channels.append(channel)
        except BadRequest:
            # Assume not joined if BadRequest occurs (e.g., user blocked bot in channel, or invalid channel)
            missing_channels.append(channel)
        except Forbidden:
            # Bot is not an admin in the channel, cannot check membership
            if update.message:
                await update.message.reply_text(
                    f"⚠️ Bot cannot check membership for {channel}. Make sure the bot is an admin in the channel.", 
                    parse_mode=ParseMode.HTML
                )
            return False

    if not missing_channels:
        return True
    
    # Construct a message with buttons for all missing channels
    join_buttons = []
    for channel in missing_channels:
        channel_name = channel.lstrip('@')
        join_buttons.append([InlineKeyboardButton(f"📢 Join {channel}", url=f"https://t.me/{channel_name}")])
    
    keyboard = InlineKeyboardMarkup(join_buttons)
    
    if update.message:
        await update.message.reply_text(
            "⚠️ <b>You must join the required channel(s) to use this bot.</b>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    return False

# ---------- Telegram Handlers ----------
start_message_user = (
    "👋 <b>Welcome to the Redeem Code Bot!</b>\n\n"
    "<b>Use the command below to redeem your code:</b>\n\n"
    "<code>/redeem &lt;code&gt;</code>\n\n"
    "Enjoy! 🤍"
)

start_message_admin = (
    "👋 <b>Welcome to the Redeem Code Bot!</b>\n\n"
    "<b>Use the command below to redeem your code:</b>\n\n"
    "<code>/redeem &lt;code&gt;</code>\n\n"
    "<b>YOU ARE AN ADMIN OF THIS BOT 💗</b>\n"
    "<b>You can access commands 👇</b>"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]]
        )
        await update.message.reply_text(
            start_message_admin,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(start_message_user, parse_mode=ParseMode.HTML)

async def show_commands_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    commands_text = (
        "🛠 <b>Admin Commands:</b>\n\n"
        "<u>Code Management:</u>\n"
        "<code>/generate &lt;code&gt; &lt;message&gt;</code> — One-time code\n"
        "<code>/generate_multi &lt;code&gt; &lt;limit&gt; &lt;optional message&gt;</code> — Multi-use code\n"
        "<code>/generate_random &lt;optional message&gt;</code> — Random one-time (reply required)\n"
        "<code>/redeem &lt;code&gt;</code> — Redeem a code\n"
        "<code>/listcodes</code> — List all codes\n"
        "<code>/deletecode &lt;code&gt;</code> — Delete a code\n\n"
        "<u>Channel Management:</u>\n"
        "<code>/addchannel &lt;@channel&gt;</code> — Add force-join channel\n"
        "<code>/delchannel &lt;@channel&gt;</code> — Delete force-join channel\n"
        "<code>/viewchannels</code> — List force-join channels\n\n"
        "<u>System:</u>\n"
        "<code>/ping</code> — System ping (latency + uptime)"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]])
    await query.edit_message_text(text=commands_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]])
    await query.edit_message_text(text=start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# --- Dynamic Channel Management Handlers ---

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n<code>/addchannel &lt;@channel_username&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    channel = context.args[0].strip()
    if not channel.startswith('@'):
        channel = f"@{channel}"
    
    global FORCE_CHANNELS
    if channel in FORCE_CHANNELS:
        await update.message.reply_text(f"⚠️ Channel <code>{channel}</code> is already in the list.", parse_mode=ParseMode.HTML)
        return

    # Optional: Check if the bot can actually access the channel (requires bot to be an admin)
    try:
        await context.bot.get_chat(channel)
    except BadRequest:
        await update.message.reply_text(f"❌ Invalid Channel Username <code>{channel}</code> or bot is not a member/admin.", parse_mode=ParseMode.HTML)
        return
    except Exception as e:
        logger.error(f"Error checking channel {channel}: {e}")
        await update.message.reply_text(f"⚠️ An error occurred while checking channel <code>{channel}</code>.", parse_mode=ParseMode.HTML)
        return

    FORCE_CHANNELS.add(channel)
    await update.message.reply_text(f"✅ Channel <code>{channel}</code> added to force-join list.", parse_mode=ParseMode.HTML)

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n<code>/delchannel &lt;@channel_username&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    channel = context.args[0].strip()
    if not channel.startswith('@'):
        channel = f"@{channel}"
    
    global FORCE_CHANNELS
    if channel not in FORCE_CHANNELS:
        await update.message.reply_text(f"⚠️ Channel <code>{channel}</code> is not in the list.", parse_mode=ParseMode.HTML)
        return

    FORCE_CHANNELS.remove(channel)
    await update.message.reply_text(f"🗑️ Channel <code>{channel}</code> removed from force-join list.", parse_mode=ParseMode.HTML)

async def view_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return

    if not FORCE_CHANNELS:
        await update.message.reply_text("ℹ️ No force-join channels currently set.", parse_mode=ParseMode.HTML)
        return

    message = "📣 <b>Current Force-Join Channels:</b>\n\n"
    for channel in sorted(list(FORCE_CHANNELS)):
        message += f"• <code>{channel}</code>\n"

    await update.message.reply_text(message, parse_mode=ParseMode.HTML)


# --- Existing Admin Handlers ---

# One-time use code
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage:\n<code>/generate &lt;code&gt; &lt;message&gt;</code>", parse_mode=ParseMode.HTML)
        return
    code = context.args[0].upper()
    custom_message = " ".join(context.args[1:])
    if code in codes:
        await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML)
        return
    codes[code] = {
        "text": custom_message,
        "used_by": None,
        "media": None,
        "created_by": update.effective_user.id
    }
    await update.message.reply_text(f"✅ Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

# Multi-use code
async def generate_multi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Usage:\n<code>/generate_multi &lt;code&gt; &lt;limit&gt; &lt;optional message&gt;</code>\n\nYou can also reply to a message with this command to attach media.",
            parse_mode=ParseMode.HTML
        )
        return
    code = context.args[0].upper()
    try:
        limit = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Limit must be a number", parse_mode=ParseMode.HTML)
        return
    custom_message = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    if code in codes:
        await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML)
        return
    media = None
    media_type = None
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        if replied.photo:
            media_type = "photo"
            media = replied.photo[-1].file_id
        elif replied.document:
            media_type = "document"
            media = replied.document.file_id
        elif replied.video:
            media_type = "video"
            media = replied.video.file_id
        elif replied.audio:
            media_type = "audio"
            media = replied.audio.file_id
        elif replied.voice:
            media_type = "voice"
            media = replied.voice.file_id
        elif replied.video_note:
            media_type = "video_note"
            media = replied.video_note.file_id
        elif replied.text:
            media_type = "text"
            media = replied.text
    codes[code] = {
        "text": custom_message,
        "used_by": [],
        "limit": limit,
        "media": {"type": media_type, "file_id": media} if media else None,
        "created_by": update.effective_user.id
    }
    await update.message.reply_text(f"✅ Multi-use Code Created!\n\nCode: <code>{code}</code>\nLimit: {limit}", parse_mode=ParseMode.HTML)

# Random one-time code
async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to a message with <code>/generate_random</code>", parse_mode=ParseMode.HTML)
        return
    while True:
        code = generate_random_code()
        if code not in codes:
            break
    custom_message = " ".join(context.args) if context.args else ""
    replied = update.message.reply_to_message
    media = None
    media_type = None
    if replied.photo:
        media_type = "photo"
        media = replied.photo[-1].file_id
    elif replied.document:
        media_type = "document"
        media = replied.document.file_id
    elif replied.video:
        media_type = "video"
        media = replied.video.file_id
    elif replied.audio:
        media_type = "audio"
        media = replied.audio.file_id
    elif replied.voice:
        media_type = "voice"
        media = replied.voice.file_id
    elif replied.video_note:
        media_type = "video_note"
        media = replied.video_note.file_id
    elif replied.text:
        media_type = "text"
        media = replied.text
    else:
        await update.message.reply_text("⚠️ Unsupported media type", parse_mode=ParseMode.HTML)
        return
    codes[code] = {
        "text": custom_message,
        "used_by": None,
        "media": {"type": media_type, "file_id": media},
        "created_by": update.effective_user.id
    }
    await update.message.reply_text(f"✅ Random Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

# Redeem command
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n<code>/redeem &lt;code&gt;</code>", parse_mode=ParseMode.HTML)
        return
    code = context.args[0].upper()
    user = update.effective_user
    user_id = user.id
    if code not in codes:
        await update.message.reply_text("❌ Invalid Code", parse_mode=ParseMode.HTML)
        return
    # Single-use code
    if codes[code].get("used_by") is None or isinstance(codes[code]["used_by"], int):
        if codes[code]["used_by"] is not None:
            await update.message.reply_text("❌ Already Redeemed", parse_mode=ParseMode.HTML)
            return
        codes[code]["used_by"] = user_id
    # Multi-use code
    else:
        if user_id in codes[code]["used_by"]:
            await update.message.reply_text("❌ You already redeemed this code!", parse_mode=ParseMode.HTML)
            return
        if len(codes[code]["used_by"]) >= codes[code]["limit"]:
            await update.message.reply_text("❌ Code redemption limit reached!", parse_mode=ParseMode.HTML)
            return
        codes[code]["used_by"].append(user_id)
    # Notify creator
    creator_id = codes[code].get("created_by")
    if creator_id:
        try:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Chat with User", url=f"tg://user?id={user_id}")]])
            await context.bot.send_message(
                chat_id=creator_id,
                text=(
                    f"🎉 <b>Code Redeemed!</b>\n\n"
                    f"• Code: <code>{code}</code>\n"
                    f"• User ID: <code>{user_id}</code>\n"
                    f"• User: {user.full_name}"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to notify creator {creator_id}: {e}")
    # Deliver reward
    media = codes[code].get("media")
    text = codes[code]["text"]
    if media:
        media_type = media["type"]
        file_id = media["file_id"]
        send_kwargs = {"chat_id": update.effective_chat.id}
        if text:
            send_kwargs["caption"] = text
            send_kwargs["parse_mode"] = ParseMode.HTML
        sent_message = None
        try:
            if media_type == "photo":
                sent_message = await context.bot.send_photo(photo=file_id, **send_kwargs)
            elif media_type == "video":
                sent_message = await context.bot.send_video(video=file_id, **send_kwargs)
            elif media_type == "document":
                sent_message = await context.bot.send_document(document=file_id, **send_kwargs)
            elif media_type == "audio":
                sent_message = await context.bot.send_audio(audio=file_id, **send_kwargs)
            elif media_type == "voice":
                sent_message = await context.bot.send_voice(voice=file_id, **send_kwargs)
            elif media_type == "video_note":
                sent_message = await context.bot.send_video_note(video_note=file_id, **send_kwargs)
            elif media_type == "text":
                msg = file_id
                if text:
                    msg += f"\n\n{text}"
                sent_message = await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to send reward media: {e}")
            await update.message.reply_text("⚠️ Failed to deliver the reward media.")

        # store message id so we can attach the screenshot button to that message
        try:
            if sent_message and hasattr(context, 'user_data'):
                context.user_data['last_reward_message_id'] = getattr(sent_message, 'message_id', None)
        except Exception:
            pass
    else:
        sent_text_msg = await update.message.reply_text(f"🎉 Success!\n\n{text}", parse_mode=ParseMode.HTML)
        try:
            if sent_text_msg and hasattr(context, 'user_data'):
                context.user_data['last_reward_message_id'] = getattr(sent_text_msg, 'message_id', None)
        except Exception:
            pass

    # After delivering reward, ask user to upload a screenshot/proof (button)
    try:
        # If the reward was sent as a message and we have its message id, reply to that message so the buttons appear under the reward.
        reply_to = None
        if hasattr(context, 'user_data') and isinstance(context.user_data, dict):
            reply_to = context.user_data.pop('last_reward_message_id', None)
        # Calling the send_screenshot_request function:
        await send_screenshot_request(update.effective_chat.id, code, context, reply_to_message_id=reply_to)
    except Exception as e:
        logger.error(f"Failed to send screenshot request button: {e}")

# List codes
async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not codes:
        await update.message.reply_text("ℹ️ No codes created yet.", parse_mode=ParseMode.HTML)
        return
    message = "📋 <b>Redeem Codes List:</b>\n\n"
    for code, info in codes.items():
        if isinstance(info["used_by"], list):  # multi-use
            used = len(info["used_by"])
            limit = info["limit"]
            message += f"• <code>{code}</code> — {used}/{limit} used\n"
        else:  # single-use
            status = "✅ Available" if info["used_by"] is None else f"❌ Redeemed by <code>{info['used_by']}</code>"
            message += f"• <code>{code}</code> — {status}\n"
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

# Delete code
async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n<code>/deletecode &lt;code&gt;</code>", parse_mode=ParseMode.HTML)
        return
    code = context.args[0].upper()
    if code not in codes:
        await update.message.reply_text("❌ Code Not Found", parse_mode=ParseMode.HTML)
        return
    del codes[code]
    await update.message.reply_text(f"🗑️ Code <code>{code}</code> deleted.", parse_mode=ParseMode.HTML)

# Styled Ping command
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Replies with styled system ping + uptime (monospace block like your screenshot).
    """
    try:
        start = time.perf_counter()
        sent = await update.message.reply_text("🏓 Pinging...")
        elapsed = (time.perf_counter() - start) * 1000  # ms

        # status category similar to the screenshot
        if elapsed < 150:
            status = "Excellent ⚡"
        elif elapsed < 300:
            status = "Good ✅"
        elif elapsed < 600:
            status = "Moderate ⚠️"
        else:
            status = "Poor ❌"

        uptime = format_uptime(time.time() - _start_time)

        # build nicely aligned mono block using fixed-width characters and spacing
        # note: HTML <code> preserves spacing in Telegram
        response_ms = f"{int(elapsed)} ms"
        # pad the labels for alignment - keep it simple and safe for varying widths
        text = (
            "<code>[ SYSTEM PING ]</code>\n\n"
            f"<code>≡ Response : {response_ms}</code>\n"
            f"<code>≡ Status   : {status}</code>\n"
            f"<code>≡ Uptime   : {uptime}</code>"
        )

        await sent.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"/ping failed: {e}")
        await update.message.reply_text("⚠️ Unable to measure ping right now.")


# --- Screenshot / Proof handling ---

async def send_screenshot_request(chat_id: int, code: str, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None):
    """Send an inline button to the user asking them to upload a screenshot/proof."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📸 Send Screenshot", callback_data=f"request_screenshot:{code}")],
            [InlineKeyboardButton("✖️ Cancel", callback_data=f"cancel_screenshot:{code}")]
        ]
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text="If you have a screenshot/proof, please send it to verify your claim.\n(Click the button below to start)",
        reply_markup=keyboard,
        reply_to_message_id=reply_to_message_id
    )

async def request_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data  # expected: request_screenshot:<CODE>
    try:
        code = data.split(':', 1)[1]
    except Exception:
        await query.message.reply_text("⚠️ Invalid request.")
        return
    if code not in codes:
        await query.message.reply_text("⚠️ This code is unknown or expired.")
        return
    creator_id = codes.get(code, {}).get("created_by")
    pending_screenshots[user.id] = {"code": code, "creator_id": creator_id, "requested_at": time.time()}
    await query.message.reply_text("📸 Please send a photo (screenshot) in this chat now. I'll forward it to the code creator.")

async def cancel_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if user.id in pending_screenshots:
        del pending_screenshots[user.id]
        await query.message.reply_text("❌ Screenshot request cancelled.")
    else:
        await query.message.reply_text("ℹ️ No pending screenshot request to cancel.")

async def handle_incoming_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    if user.id not in pending_screenshots:
        # optional: ignore silently or inform user
        await message.reply_text("ℹ️ If you want to send proof for a redeemed code, click the 'Send Screenshot' button under your reward first.")
        return
    info = pending_screenshots.pop(user.id)
    code = info.get('code')
    creator_id = info.get('creator_id')

    caption = (
        f"📸 <b>Screenshot / Proof Received</b>\n\n"
        f"• Code: <code>{code}</code>\n"
        f"• From: <code>{user.id}</code> — {user.full_name}\n"
        f"• Chat: <code>{message.chat.id}</code>"
    )

    try:
        # prefer sending original photo file
        if message.photo:
            file_id = message.photo[-1].file_id
            # forward to creator if exists
            if creator_id:
                await context.bot.send_photo(chat_id=creator_id, photo=file_id, caption=caption, parse_mode=ParseMode.HTML)
            else:
                # if creator is unknown, inform the sender (do not broadcast to all admins)
                await message.reply_text("⚠️ Unable to forward: the code creator is unknown. Please contact support/admin.")
                return
        elif message.document and (message.document.mime_type or '').startswith('image'):
            file_id = message.document.file_id
            if creator_id:
                await context.bot.send_document(chat_id=creator_id, document=file_id, caption=caption, parse_mode=ParseMode.HTML)
            else:
                await message.reply_text("⚠️ Unable to forward: the code creator is unknown. Please contact support/admin.")
                return
        else:
            # unsupported type
            await message.reply_text("⚠️ Unsupported file type. Please send a photo or image file.")
            return

        await message.reply_text("✅ Screenshot received and forwarded to the code creator. Thank you!")
    except Exception as e:
        logger.error(f"Failed to process incoming screenshot: {e}")
        await message.reply_text("⚠️ Failed to forward screenshot. Please try again later.")


# ---------- Flask status page & endpoints - Updated for direct Open Bot link ----------
flask_app = Flask(__name__)

STATUS_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Redeem Code Bot — Termux-style Status</title>
  <style>
    :root{--bg:#0b0f14;--card:#071019;--accent:#00d1ff;--muted:#8aa0b1;--mono: 'SFMono-Regular', Menlo, Monaco, 'Roboto Mono', monospace;}
    html,body{height:100%;margin:0;background:linear-gradient(180deg,#020612 0%, #071226 45%, #08131b 100%);font-family:Inter, system-ui, Arial;color:#e6f3fb}
    .wrap{min-height:100%;display:flex;align-items:center;justify-content:center;padding:32px}
    .card{width:920px;max-width:96vw;background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));border-radius:14px;padding:22px;box-shadow:0 10px 40px rgba(2,6,23,0.7);display:grid;grid-template-columns:260px 1fr;gap:18px}
    .side{display:flex;flex-direction:column;align-items:center;gap:14px}
    .termux-badge{width:160px;height:160px;border-radius:18px;background:linear-gradient(135deg,#001217,#00262c);display:flex;align-items:center;justify-content:center;box-shadow:inset 0 -6px 40px rgba(0,0,0,0.6),0 8px 30px rgba(0,0,0,0.6);position:relative;overflow:hidden}
    .termux-logo{font-family:var(--mono);font-weight:700;color:var(--accent);letter-spacing:1px;font-size:34px;text-transform:uppercase}
    .meta{font-size:13px;color:var(--muted);text-align:center}
    .btn-row{display:flex;gap:8px}
    /* Updated styles for <a> tag to look like button */
    .btn, .btn-link {
        padding: 8px 10px;
        border-radius: 10px;
        background: transparent;
        border: 1px solid rgba(255,255,255,0.04);
        color: var(--muted);
        font-size: 13px;
        cursor: pointer;
        text-decoration: none; /* For link */
        text-align: center;
        display: inline-block;
    }
    .btn.primary{background:linear-gradient(90deg, rgba(0,209,255,0.08), rgba(0,150,255,0.04));border:1px solid rgba(0,209,255,0.14);color:var(--accent)}
    .terminal{background:#001014;border-radius:10px;padding:18px;box-shadow:inset 0 2px 4px rgba(0,0,0,0.6);height:260px;overflow:hidden;border:1px solid rgba(255,255,255,0.02)}
    .term-top{display:flex;gap:8px;align-items:center;margin-bottom:8px}
    .lights{display:flex;gap:6px}
    .light{width:10px;height:10px;border-radius:50%}
    .l-red{background:#ff6b6b}
    .l-yel{background:#ffd166}
    .l-grn{background:#17e6a2}
    .terminal-lines{font-family:var(--mono);color:#cdeef8;font-size:13.5px;line-height:1.45;white-space:pre-wrap}
    .cursor{display:inline-block;width:9px;height:18px;background:var(--accent);vertical-align:middle;margin-left:3px;animation:blink 1s steps(2) infinite}
    @keyframes blink{0%{opacity:1}50%{opacity:0}100%{opacity:1}}
    .progress-wrap{margin-top:12px}
    .progress{height:12px;background:rgba(255,255,255,0.03);border-radius:8px;overflow:hidden}
    .bar{height:100%;width:0%;background:linear-gradient(90deg,var(--accent),#6ce1ff);border-radius:8px}
    .progress-meta{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:8px}
    .info{display:flex;flex-direction:column;gap:12px}
    .title{font-size:18px;font-weight:600}
    .sub{font-size:13px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
    .stat{background:var(--card);padding:10px;border-radius:8px;font-size:13px}
    .stat b{display:block;font-size:16px;color:var(--accent);margin-bottom:6px}
    @media (max-width:760px){.card{grid-template-columns:1fr}.termux-badge{width:120px;height:120px}.terminal{height:220px}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="side">
        <div class="termux-badge" aria-hidden>
          <div class="termux-logo">termux</div>
        </div>
        <div class="meta">
          <div><strong>Redeem Code Bot</strong></div>
          <div style="margin-top:6px;color:var(--muted)">Dark Termux-style status</div>
        </div>
        <div class="btn-row" style="margin-top:8px">
          <button class="btn primary" id="restartBtn">Restart Bot</button>
          <a href="tg://resolve?domain=zeusopstore_bot" target="_blank" class="btn">Open Bot</a>
        </div>
      </div>

      <div class="info">
        <div>
          <div class="title">Terminal</div>
          <div class="sub">Simulated Termux boot animation. Page auto-fills live status from /status.</div>
        </div>

        <div class="terminal" role="img" aria-label="Termux terminal simulation">
          <div class="term-top">
            <div class="lights"><span class="light l-red"></span><span class="light l-yel"></span><span class="light l-grn"></span></div>
            <div style="margin-left:10px;color:var(--muted);font-size:13px">termux@render:~</div>
          </div>
          <div class="terminal-lines" id="terminalLines"></div>
        </div>

        <div class="progress-wrap">
          <div class="progress" aria-hidden>
            <div class="bar" id="bar"></div>
          </div>
          <div class="progress-meta"><span id="progressText">Initializing...</span><span id="percent">0%</span></div>
        </div>

        <div class="grid">
          <div class="stat"><b id="uptime">—</b>Uptime</div>
          <div class="stat"><b id="version">—</b>Version</div>
          <div class="stat"><b id="users">—</b>Active Users</div>
          <div class="stat"><b id="chan">—</b>Channels Required</div>
        </div>
      </div>
    </div>
  </div>

<script>
  const lines_template = [
    'booting termux-emulator...\\n',
    'loading modules: telegram-core, flask-host\\n',
    'checking force-join channels... {chan_count} found\\n',
    'verifying token... OK\\n',
    'starting webhook / polling... OK\\n',
    'initializing redeem subsystem...\\n',
    'scanning codes database... {codes_count} codes found\\n',
    'ready. welcome to {bot_name}\\n'
  ];

  async function fetchAndStart() {
    try {
      const res = await fetch('/status');
      const json = await res.json();
      const lines = lines_template.map(l => l.replace('{chan_count}', json.force_channel_count).replace('{bot_name}', json.bot_name).replace('{codes_count}', json.codes_count));
      startTypewriter(lines, json);
    } catch (e) {
      startTypewriter(['failed to fetch /status\\n', 'running with fallback values\\n']);
    }
  }

  function startTypewriter(lines, status) {
    const out = document.getElementById('terminalLines');
    const bar = document.getElementById('bar');
    const pct = document.getElementById('percent');
    const ptext = document.getElementById('progressText');

    if (status) {
      document.getElementById('uptime').innerText = status.uptime;
      document.getElementById('version').innerText = status.version;
      document.getElementById('users').innerText = status.active_users;
      document.getElementById('chan').innerText = status.force_channel_count;
    }

    let li = 0;
    let totalChars = lines.join('').length;
    let printed = 0;

    function typeNextLine() {
      if (li >= lines.length) {
        ptext.innerText = 'Done';
        bar.style.width = '100%';
        pct.innerText = '100%';
        out.innerHTML += '\\n';
        return;
      }
      const line = lines[li];
      let pos = 0;
      const speed = 12 + Math.random() * 18;
      const iv = setInterval(() => {
        out.innerHTML += line[pos] === '\\n' ? '<br/>' : line[pos];
        pos += 1;
        printed += 1;
        const percent = Math.min(99, Math.round((printed / totalChars) * 100));
        bar.style.width = percent + '%';
        pct.innerText = percent + '%';
        if (pos >= line.length) {
          clearInterval(iv);
          li += 1;
          setTimeout(typeNextLine, 220 + Math.random() * 220);
        }
      }, speed);
    }
    typeNextLine();
  }

  document.getElementById('restartBtn').addEventListener('click', async () => {
    if (!confirm('Restart Bot? (this will call a protected endpoint)')) return;
    const resp = await fetch('/restart', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({secret: '{{WEB_SECRET}}'})
    });
    const j = await resp.json();
    alert(j.message || 'ok');
  });
  // The 'Open Bot' JavaScript handler has been removed as it's now a direct HTML link.

  fetchAndStart();
</script>
</body>
</html>
"""

@flask_app.route("/")
def home():
    rendered = render_template_string(STATUS_HTML, WEB_SECRET=WEB_SECRET)
    return Response(rendered, mimetype="text/html")

@flask_app.route("/status")
def status():
    uptime = format_uptime(time.time() - _start_time)
    active_users = compute_active_users()
    return jsonify({
        "uptime": uptime,
        "version": BOT_VERSION,
        "active_users": active_users,
        "force_channel_count": len(FORCE_CHANNELS), # Changed to count
        "bot_name": "Redeem Code Bot",
        "codes_count": len(codes)
    })

def _check_secret(req_json):
    if not WEB_SECRET:
        return False
    return req_json.get("secret") == WEB_SECRET

@flask_app.route("/restart", methods=["POST"])
def http_restart():
    data = request.get_json(silent=True) or {}
    if not _check_secret(data):
        return jsonify({"ok": False, "message": "unauthorized"}), 401
    logger.info("Received /restart via HTTP - secret validated (no restart performed, placeholder).")
    return jsonify({"ok": True, "message": "restart endpoint received (placeholder)."}), 200

# The /open Flask route is no longer strictly necessary if the button is a direct link, 
# but we leave it as a placeholder just in case:
@flask_app.route("/open", methods=["POST"])
def http_open():
    data = request.get_json(silent=True) or {}
    if not _check_secret(data):
        return jsonify({"ok": False, "message": "unauthorized"}), 401
    logger.info("Received /open via HTTP - secret validated (placeholder).")
    return jsonify({"ok": True, "message": "open endpoint received (placeholder)."}), 200

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Base commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("ping", ping))

    # Admin Code Management
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("generate_multi", generate_multi))
    app.add_handler(CommandHandler("generate_random", generate_random))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("deletecode", deletecode))

    # Admin Channel Management (NEW)
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("viewchannels", view_channels))

    # Admin Button Callbacks
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="show_commands"))
    app.add_handler(CallbackQueryHandler(back_to_start_callback, pattern="back_to_start"))
    
    # Screenshot handlers
    app.add_handler(CallbackQueryHandler(request_screenshot_callback, pattern=r"^request_screenshot:"))
    app.add_handler(CallbackQueryHandler(cancel_screenshot_callback, pattern=r"^cancel_screenshot:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_incoming_image))

    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
