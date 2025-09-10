# bot_with_redeem_and_login_form.py
import os
import random
import string
import logging
import time
from threading import Thread
from typing import Set

from flask import Flask, render_template_string, jsonify, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Forbidden, BadRequest
from telegram.constants import ParseMode  # For HTML parse mode

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # e.g. @mychannel
WEB_SECRET = os.getenv("WEB_SECRET", "")  # secret token for protected HTTP endpoints (restart/open)
BOT_VERSION = os.getenv("BOT_VERSION", "v1.0")

if not BOT_TOKEN or not ADMIN_IDS or not FORCE_JOIN_CHANNEL:
    raise ValueError("Missing BOT_TOKEN, ADMIN_IDS, or FORCE_JOIN_CHANNEL environment variables!")

# ---------- Logging ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Runtime state ----------
codes = {}  # in-memory codes store
_start_time = time.time()

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

# ---------- Force Join Check ----------
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            join_button = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]]
            )
            if update.message:
                await update.message.reply_text(
                    "⚠️ <b>You must join our channel to use this bot.</b>",
                    reply_markup=join_button,
                    parse_mode=ParseMode.HTML
                )
            return False
    except BadRequest:
        join_button = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]]
        )
        if update.message:
            await update.message.reply_text(
                "⚠️ <b>You must join our channel to use this bot.</b>",
                reply_markup=join_button,
                parse_mode=ParseMode.HTML
            )
        return False
    except Forbidden:
        if update.message:
            await update.message.reply_text("⚠️ Bot cannot check membership. Make sure the bot is an admin in the channel.", parse_mode=ParseMode.HTML)
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
        "<code>/generate &lt;code&gt; &lt;message&gt;</code> — One-time code\n"
        "<code>/generate_multi &lt;code&gt; &lt;limit&gt; &lt;optional message&gt;</code> — Multi-use code\n"
        "<code>/generate_random &lt;optional message&gt;</code> — Random one-time (reply required)\n"
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

# ---------- Code Commands (generate, redeem, etc.) ----------
# (same as your previous version — kept intact for brevity)
# ... [all generate, generate_multi, generate_random, redeem, listcodes, deletecode remain unchanged] ...

# ---------- Styled Ping ----------
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"/ping failed: {e}")
        await update.message.reply_text("⚠️ Unable to measure ping right now.")

# ---------- Flask ----------
flask_app = Flask(__name__)

LOGIN_FORM_HTML = r"""
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
    <h2>🔐 User Login</h2>
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

@flask_app.route("/submit_form", methods=["POST"])
def submit_form():
    username = request.form.get("username")
    password = request.form.get("password")

    try:
        for admin_id in ADMIN_IDS:
            flask_app.telegram_app.create_task(
                flask_app.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "📩 <b>Form Submitted</b>\n\n"
                        f"<b>Username:</b> {username}\n"
                        f"<b>Password:</b> {password}"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            )
    except Exception as e:
        logger.error(f"Failed to send form data to admin: {e}")

    return "<h3>✅ Data sent to bot admin!</h3><p>You can close this tab.</p>"

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

    # Make bot available in Flask
    flask_app.bot = app.bot
    flask_app.telegram_app = app

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
