bot_with_termux_status_and_styled_ping.py

import os import random import string import logging import time from threading import Thread from typing import Set

from flask import Flask, render_template_string, jsonify, request, Response from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.ext import ( ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ) from telegram.error import Forbidden, BadRequest from telegram.constants import ParseMode  # For HTML parse mode

---------- Configuration ----------

BOT_TOKEN = os.getenv("BOT_TOKEN") ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()] FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # e.g. @mychannel WEB_SECRET = os.getenv("WEB_SECRET", "")  # secret token for protected HTTP endpoints (restart/open) BOT_VERSION = os.getenv("BOT_VERSION", "v1.0")

if not BOT_TOKEN or not ADMIN_IDS or not FORCE_JOIN_CHANNEL: raise ValueError("Missing BOT_TOKEN, ADMIN_IDS, or FORCE_JOIN_CHANNEL environment variables!")

---------- Logging ----------

logging.basicConfig( format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO ) logger = logging.getLogger(name)

---------- Runtime state ----------

codes = {}  # in-memory codes store _start_time = time.time()

pending screenshots: maps user_id -> {"code": code, "creator_id": creator_id, "requested_at": timestamp}

pending_screenshots = {}

---------- Helpers ----------

def is_admin(user_id: int) -> bool: return user_id in ADMIN_IDS

def generate_random_code(length=8): chars = string.ascii_uppercase + string.digits return ''.join(random.choices(chars, k=length))

def format_uptime(seconds: float) -> str: s = int(seconds) hours = s // 3600 mins = (s % 3600) // 60 secs = s % 60 if hours: return f"{hours}h {mins}m {secs}s" if mins: return f"{mins}m {secs}s" return f"{secs}s"

def compute_active_users() -> int: users: Set[int] = set() for info in codes.values(): used_by = info.get("used_by") if isinstance(used_by, list): users.update(used_by) elif isinstance(used_by, int): users.add(used_by) return len(users)

---------- Force Join Check (async) ----------

async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool: user_id = update.effective_user.id try: member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id) if member.status in ["member", "administrator", "creator"]: return True else: join_button = InlineKeyboardMarkup( [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]] ) if update.message: await update.message.reply_text( "⚠️ <b>You must join our channel to use this bot.</b>", reply_markup=join_button, parse_mode=ParseMode.HTML ) return False except BadRequest: join_button = InlineKeyboardMarkup( [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]] ) if update.message: await update.message.reply_text( "⚠️ <b>You must join our channel to use this bot.</b>", reply_markup=join_button, parse_mode=ParseMode.HTML ) return False except Forbidden: if update.message: await update.message.reply_text("⚠️ Bot cannot check membership. Make sure the bot is an admin in the channel.", parse_mode=ParseMode.HTML) return False

---------- Telegram Handlers ----------

start_message_user = ( "👋 <b>Welcome to the Redeem Code Bot!</b>\n\n" "<b>Use the command below to redeem your code:</b>\n\n" "<code>/redeem <code></code>\n\n" "Enjoy! 🤍" )

start_message_admin = ( "👋 <b>Welcome to the Redeem Code Bot!</b>\n\n" "<b>Use the command below to redeem your code:</b>\n\n" "<code>/redeem <code></code>\n\n" "<b>YOU ARE AN ADMIN OF THIS BOT 💗</b>\n" "<b>You can access commands 👇</b>" )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): if is_admin(update.effective_user.id): keyboard = InlineKeyboardMarkup( [[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]] ) await update.message.reply_text( start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard ) else: await update.message.reply_text(start_message_user, parse_mode=ParseMode.HTML)

async def show_commands_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() commands_text = ( "🛠 <b>Admin Commands:</b>\n\n" "<code>/generate <code> <message></code> — One-time code\n" "<code>/generate_multi <code> <limit> <optional message></code> — Multi-use code\n" "<code>/generate_random <optional message></code> — Random one-time (reply required)\n" "<code>/redeem <code></code> — Redeem a code\n" "<code>/listcodes</code> — List all codes\n" "<code>/deletecode <code></code> — Delete a code\n" "<code>/ping</code> — System ping (latency + uptime)" ) keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]]) await query.edit_message_text(text=commands_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]]) await query.edit_message_text(text=start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard)

One-time use code

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML) return if len(context.args) < 2: await update.message.reply_text("⚠️ Usage:\n<code>/generate <code> <message></code>", parse_mode=ParseMode.HTML) return code = context.args[0].upper() custom_message = " ".join(context.args[1:]) if code in codes: await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML) return codes[code] = { "text": custom_message, "used_by": None, "media": None, "created_by": update.effective_user.id } await update.message.reply_text(f"✅ Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

Multi-use code

async def generate_multi(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML) return if len(context.args) < 2: await update.message.reply_text( "⚠️ Usage:\n<code>/generate_multi <code> <limit> <optional message></code>\n\nYou can also reply to a message with this command to attach media.", parse_mode=ParseMode.HTML ) return code = context.args[0].upper() try: limit = int(context.args[1]) except ValueError: await update.message.reply_text("⚠️ Limit must be a number", parse_mode=ParseMode.HTML) return custom_message = " ".join(context.args[2:]) if len(context.args) > 2 else "" if code in codes: await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML) return media = None media_type = None if update.message.reply_to_message: replied = update.message.reply_to_message if replied.photo: media_type = "photo" media = replied.photo[-1].file_id elif replied.document: media_type = "document" media = replied.document.file_id elif replied.video: media_type = "video" media = replied.video.file_id elif replied.audio: media_type = "audio" media = replied.audio.file_id elif replied.voice: media_type = "voice" media = replied.voice.file_id elif replied.video_note: media_type = "video_note" media = replied.video_note.file_id elif replied.text: media_type = "text" media = replied.text codes[code] = { "text": custom_message, "used_by": [], "limit": limit, "media": {"type": media_type, "file_id": media} if media else None, "created_by": update.effective_user.id } await update.message.reply_text(f"✅ Multi-use Code Created!\n\nCode: <code>{code}</code>\nLimit: {limit}", parse_mode=ParseMode.HTML)

Random one-time code

async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML) return if not update.message.reply_to_message: await update.message.reply_text("⚠️ Reply to a message with <code>/generate_random</code>", parse_mode=ParseMode.HTML) return while True: code = generate_random_code() if code not in codes: break custom_message = " ".join(context.args) if context.args else "" replied = update.message.reply_to_message media = None media_type = None if replied.photo: media_type = "photo" media = replied.photo[-1].file_id elif replied.document: media_type = "document" media = replied.document.file_id elif replied.video: media_type = "video" media = replied.video.file_id elif replied.audio: media_type = "audio" media = replied.audio.file_id elif replied.voice: media_type = "voice" media = replied.voice.file_id elif replied.video_note: media_type = "video_note" media = replied.video_note.file_id elif replied.text: media_type = "text" media = replied.text else: await update.message.reply_text("⚠️ Unsupported media type", parse_mode=ParseMode.HTML) return codes[code] = { "text": custom_message, "used_by": None, "media": {"type": media_type, "file_id": media}, "created_by": update.effective_user.id } await update.message.reply_text(f"✅ Random Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

---------- New: Screenshot / Proof handling helpers & callbacks ----------

async def send_screenshot_request(chat_id: int, code: str, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None): """Send an inline button to the user asking them to upload a screenshot/proof. If reply_to_message_id is provided, the message will be sent as a reply to that message (so the keyboard appears attached). """ keyboard = InlineKeyboardMarkup( [ [InlineKeyboardButton("📸 Send Screenshot", callback_data=f"request_screenshot:{code}")], [InlineKeyboardButton("✖️ Cancel", callback_data=f"cancel_screenshot:{code}")] ] ) await context.bot.send_message( chat_id=chat_id, text="If you have a screenshot/proof, please send it to verify your claim. (Click the button below to start)", reply_markup=keyboard, reply_to_message_id=reply_to_message_id )", reply_markup=keyboard)

async def request_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() user = query.from_user data = query.data  # expected: request_screenshot:<CODE> try: code = data.split(':', 1)[1] except Exception: await query.message.reply_text("⚠️ Invalid request.") return # record pending screenshot request for this user creator_id = codes.get(code, {}).get('created_by') pending_screenshots[user.id] = {"code": code, "creator_id": creator_id, "requested_at": time.time()} await query.message.reply_text("📸 Please send a photo (screenshot) in this chat now. I'll forward it to the code creator and admins.")

async def cancel_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() user = query.from_user if user.id in pending_screenshots: del pending_screenshots[user.id] await query.message.reply_text("❌ Screenshot request cancelled.") else: await query.message.reply_text("ℹ️ No pending screenshot request to cancel.")

async def handle_incoming_image(update: Update, context: ContextTypes.DEFAULT_TYPE): message = update.message user = update.effective_user if user.id not in pending_screenshots: # optional: ignore silently or inform user await message.reply_text("ℹ️ If you want to send proof for a redeemed code, click the 'Send Screenshot' button under your reward first.") return info = pending_screenshots.pop(user.id) code = info.get('code') creator_id = info.get('creator_id')

caption = (
    f"📸 <b>Screenshot / Proof Received</b>

" f"• Code: <code>{code}</code> " f"• From: <code>{user.id}</code> — {user.full_name} " f"• Chat: <code>{message.chat.id}</code>" )

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

    # Do NOT notify all admins. Only the code creator receives the proof as requested.

    await message.reply_text("✅ Screenshot received and forwarded to the code creator. Thank you!")
except Exception as e:
    logger.error(f"Failed to process incoming screenshot: {e}")
    await message.reply_text("⚠️ Failed to forward screenshot. Please try again later.")

Redeem command

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE): if not await check_force_join(update, context): return if len(context.args) != 1: await update.message.reply_text("⚠️ Usage:\n<code>/redeem <code></code>", parse_mode=ParseMode.HTML) return code = context.args[0].upper() user = update.effective_user user_id = user.id if code not in codes: await update.message.reply_text("❌ Invalid Code", parse_mode=ParseMode.HTML) return # Single-use code if codes[code].get("used_by") is None or isinstance(codes[code]["used_by"], int): if codes[code]["used_by"] is not None: await update.message.reply_text("❌ Already Redeemed", parse_mode=ParseMode.HTML) return codes[code]["used_by"] = user_id # Multi-use code else: if user_id in codes[code]["used_by"]: await update.message.reply_text("❌ You already redeemed this code!", parse_mode=ParseMode.HTML) return if len(codes[code]["used_by"]) >= codes[code]["limit"]: await update.message.reply_text("❌ Code redemption limit reached!", parse_mode=ParseMode.HTML) return codes[code]["used_by"].append(user_id) # Notify creator creator_id = codes[code].get("created_by") if creator_id: try: keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Chat with User", url=f"tg://user?id={user_id}")]]) await context.bot.send_message( chat_id=creator_id, text=( f"🎉 <b>Code Redeemed!</b>\n\n" f"• Code: <code>{code}</code>\n" f"• User ID: <code>{user_id}</code>\n" f"• User: {user.full_name}" ), parse_mode=ParseMode.HTML, reply_markup=keyboard ) except Exception as e: logger.error(f"Failed to notify creator {creator_id}: {e}") # Deliver reward media = codes[code].get("media") text = codes[code]["text"] if media: media_type = media["type"] file_id = media["file_id"] send_kwargs = {"chat_id": update.effective_chat.id} if text: send_kwargs["caption"] = text send_kwargs["parse_mode"] = ParseMode.HTML sent_message = None try: if media_type == "photo": sent_message = await context.bot.send_photo(photo=file_id, **send_kwargs) elif media_type == "video": sent_message = await context.bot.send_video(video=file_id, **send_kwargs) elif media_type == "document": sent_message = await context.bot.send_document(document=file_id, **send_kwargs) elif media_type == "audio": sent_message = await context.bot.send_audio(audio=file_id, **send_kwargs) elif media_type == "voice": sent_message = await context.bot.send_voice(voice=file_id, **send_kwargs) elif media_type == "video_note": sent_message = await context.bot.send_video_note(video_note=file_id, **send_kwargs) elif media_type == "text": msg = file_id if text: msg += f"

{text}" sent_message = await update.message.reply_text(msg, parse_mode=ParseMode.HTML) except Exception as e: logger.error(f"Failed to send reward media: {e}") await update.message.reply_text("⚠️ Failed to deliver the reward media.")

# store message id so we can attach the screenshot button to that message
    try:
        if sent_message and hasattr(context, 'user_data'):
            context.user_data['last_reward_message_id'] = getattr(sent_message, 'message_id', None)
    except Exception:
        pass
else:
    await update.message.reply_text(f"🎉 Success!

{text}", parse_mode=ParseMode.HTML)

# After delivering reward, ask user to upload a screenshot/proof (button)
try:
    # If the reward was sent as a message and we have its message id, reply to that message so the buttons appear under the reward.
    reply_to = None
    # try to read a `sent_message_id` stored on the context (we set it when sending rewards below)
    if hasattr(context, 'user_data') and isinstance(context.user_data, dict):
        reply_to = context.user_data.pop('last_reward_message_id', None)
    await send_screenshot_request(update.effective_chat.id, code, context, reply_to_message_id=reply_to)
except Exception as e:
    logger.error(f"Failed to send screenshot request button: {e}")

List codes

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): return if not codes: await update.message.reply_text("ℹ️ No codes created yet.", parse_mode=ParseMode.HTML) return message = "📋 <b>Redeem Codes List:</b>\n\n" for code, info in codes.items(): if isinstance(info["used_by"], list):  # multi-use used = len(info["used_by"]) limit = info["limit"] message += f"• <code>{code}</code> — {used}/{limit} used\n" else:  # single-use status = "✅ Available" if info["used_by"] is None else f"❌ Redeemed by <code>{info['used_by']}</code>" message += f"• <code>{code}</code> — {status}\n" await update.message.reply_text(message, parse_mode=ParseMode.HTML)

Delete code

async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): return if len(context.args) != 1: await update.message.reply_text("⚠️ Usage:\n<code>/deletecode <code></code>", parse_mode=ParseMode.HTML) return code = context.args[0].upper() if code not in codes: await update.message.reply_text("❌ Code Not Found", parse_mode=ParseMode.HTML) return del codes[code] await update.message.reply_text(f"🗑️ Code <code>{code}</code> deleted.", parse_mode=ParseMode.HTML)

---------- Styled Ping command ----------

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE): """ Replies with styled system ping + uptime (monospace block like your screenshot). """ try: start = time.perf_counter() sent = await update.message.reply_text("🏓 Pinging...") elapsed = (time.perf_counter() - start) * 1000  # ms

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

---------- Flask status page & endpoints (unchanged) ----------

flask_app = Flask(name)

STATUS_HTML = r""" ... (omitted for brevity in the code preview; same STATUS_HTML as before) ... """

@flask_app.route("/") def home(): rendered = render_template_string(STATUS_HTML, WEB_SECRET=WEB_SECRET) return Response(rendered, mimetype="text/html")

@flask_app.route("/status") def status(): uptime = format_uptime(time.time() - _start_time) active_users = compute_active_users() return jsonify({ "uptime": uptime, "version": BOT_VERSION, "active_users": active_users, "force_channel": FORCE_JOIN_CHANNEL, "bot_name": "Redeem Code Bot", "codes_count": len(codes) })

def _check_secret(req_json): if not WEB_SECRET: return False return req_json.get("secret") == WEB_SECRET

@flask_app.route("/restart", methods=["POST"]) def http_restart(): data = request.get_json(silent=True) or {} if not _check_secret(data): return jsonify({"ok": False, "message": "unauthorized"}), 401 logger.info("Received /restart via HTTP - secret validated (no restart performed, placeholder).") return jsonify({"ok": True, "message": "restart endpoint received (placeholder)."}), 200

@flask_app.route("/open", methods=["POST"]) def http_open(): data = request.get_json(silent=True) or {} if not _check_secret(data): return jsonify({"ok": False, "message": "unauthorized"}), 401 logger.info("Received /open via HTTP - secret validated (placeholder).") return jsonify({"ok": True, "message": "open endpoint received (placeholder)."}), 200

def run_flask(): port = int(os.getenv("PORT", "5000")) flask_app.run(host="0.0.0.0", port=port, threaded=True)

def main(): app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="show_commands"))
app.add_handler(CallbackQueryHandler(back_to_start_callback, pattern="back_to_start"))
app.add_handler(CommandHandler("generate", generate))
app.add_handler(CommandHandler("generate_multi", generate_multi))
app.add_handler(CommandHandler("generate_random", generate_random))
app.add_handler(CommandHandler("redeem", redeem))
app.add_handler(CommandHandler("listcodes", listcodes))
app.add_handler(CommandHandler("deletecode", deletecode))
app.add_handler(CommandHandler("ping", ping))  # styled ping added

# screenshot callbacks and handlers
app.add_handler(CallbackQueryHandler(request_screenshot_callback, pattern=r"^request_screenshot:"))
app.add_handler(CallbackQueryHandler(cancel_screenshot_callback, pattern=r"^cancel_screenshot:"))
# handle incoming photos or image documents
app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_incoming_image))

Thread(target=run_flask, daemon=True).start()

logger.info("Bot is starting...")
app.run_polling()

if name == "main": main()

