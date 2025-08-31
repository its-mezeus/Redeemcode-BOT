import os
import random
import string
import logging
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Forbidden, BadRequest

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load config from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # Example: @mychannel

if not BOT_TOKEN or not ADMIN_IDS or not FORCE_JOIN_CHANNEL:
    raise ValueError("Missing BOT_TOKEN, ADMIN_IDS, or FORCE_JOIN_CHANNEL environment variables!")

codes = {}

start_message_user = (
    "👋 *Welcome to the Redeem Code Bot!*\n\n"
    "*Use the command below to redeem your code:*\n\n"
    "`/redeem <code>`\n\n"
    "Enjoy! 🤍"
)

start_message_admin = (
    "👋 *Welcome to the Redeem Code Bot!*\n\n"
    "*Use the command below to redeem your code:*\n\n"
    "`/redeem <code>`\n\n"
    "*YOU ARE AN ADMIN OF THIS BOT 💗*\n"
    "*You can access commands 👇*"
)

# Helper: check admin
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# 🔹 Force Join Check
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            raise BadRequest("User not joined")
    except BadRequest:
        join_button = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]]
        )
        await update.message.reply_text(
            "⚠️ *You must join our channel to use this bot.*",
            reply_markup=join_button,
            parse_mode="Markdown"
        )
        return False
    except Forbidden:
        await update.message.reply_text("⚠️Join @NECKsERA and Start the Bot.\nJoin Channel and Try Again.")
        return False

# Code Generator
def generate_random_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

# ---------------- Commands ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]]
        )
        await update.message.reply_text(
            start_message_admin,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(start_message_user, parse_mode="Markdown")

# 📜 Show commands callback
async def show_commands_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    commands_text = (
        "🛠 *Admin Commands:*\n\n"
        "`/generate <code> <message>` — One-time code\n"
        "`/generate_multi <code> <limit> <optional message>` — Multi-use code\n"
        "`/generate_random <optional message>` — Random one-time (reply required)\n"
        "`/redeem <code>` — Redeem a code\n"
        "`/listcodes` — List all codes\n"
        "`/deletecode <code>` — Delete a code"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]]
    )

    await query.edit_message_text(
        text=commands_text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ⬅️ Back callback
async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]]
    )

    await query.edit_message_text(
        text=start_message_admin,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# One-time use code
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode="Markdown")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage:\n`/generate <code> <message>`", parse_mode="Markdown")
        return

    code = context.args[0].upper()
    custom_message = " ".join(context.args[1:])

    if code in codes:
        await update.message.reply_text("⚠️ Duplicate Code!", parse_mode="Markdown")
        return

    codes[code] = {"text": custom_message, "used_by": None, "media": None}
    await update.message.reply_text(f"✅ Code Created!\n\nCode: `{code}`", parse_mode="Markdown")

# Multi-use code (with or without media)
async def generate_multi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode="Markdown")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Usage:\n`/generate_multi <code> <limit> <optional message>`\n\n"
            "You can also reply to a message with this command to attach media.",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].upper()
    try:
        limit = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Limit must be a number", parse_mode="Markdown")
        return

    custom_message = " ".join(context.args[2:]) if len(context.args) > 2 else ""

    if code in codes:
        await update.message.reply_text("⚠️ Duplicate Code!", parse_mode="Markdown")
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
        "media": {"type": media_type, "file_id": media} if media else None
    }

    await update.message.reply_text(
        f"✅ Multi-use Code Created!\n\nCode: `{code}`\nLimit: {limit}",
        parse_mode="Markdown"
    )

# Random one-time code
async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode="Markdown")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to a message with `/generate_random`", parse_mode="Markdown")
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
        await update.message.reply_text("⚠️ Unsupported media type", parse_mode="Markdown")
        return

    codes[code] = {"text": custom_message, "used_by": None, "media": {"type": media_type, "file_id": media}}
    await update.message.reply_text(f"✅ Random Code Created!\n\nCode: `{code}`", parse_mode="Markdown")

# Redeem command (supports single & multi-use)
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return

    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n`/redeem <code>`", parse_mode="Markdown")
        return

    code = context.args[0].upper()
    user = update.effective_user
    user_id = user.id

    if code not in codes:
        await update.message.reply_text("❌ Invalid Code", parse_mode="Markdown")
        return

    # Single-use code
    if codes[code].get("used_by") is None or isinstance(codes[code]["used_by"], int):
        if codes[code]["used_by"] is not None:
            await update.message.reply_text("❌ Already Redeemed", parse_mode="Markdown")
            return
        codes[code]["used_by"] = user_id

    # Multi-use code
    else:
        if user_id in codes[code]["used_by"]:
            await update.message.reply_text("❌ You already redeemed this code!", parse_mode="Markdown")
            return
        if len(codes[code]["used_by"]) >= codes[code]["limit"]:
            await update.message.reply_text("❌ Code redemption limit reached!", parse_mode="Markdown")
            return
        codes[code]["used_by"].append(user_id)

    # Notify Admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🎉 *Code Redeemed!*\n\n"
                    f"• Code: `{code}`\n"
                    f"• User ID: `{user_id}`\n"
                    f"• User: [{user.full_name}](tg://user?id={user_id})"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    # Deliver reward
    media = codes[code].get("media")
    text = codes[code]["text"]

    if media:
        media_type = media["type"]
        file_id = media["file_id"]

        send_kwargs = {"chat_id": update.effective_chat.id}
        if text:
            send_kwargs["caption"] = text
            send_kwargs["parse_mode"] = "Markdown"

        if media_type == "photo":
            await context.bot.send_photo(photo=file_id, **send_kwargs)
        elif media_type == "video":
            await context.bot.send_video(video=file_id, **send_kwargs)
        elif media_type == "document":
            await context.bot.send_document(document=file_id, **send_kwargs)
        elif media_type == "audio":
            await context.bot.send_audio(audio=file_id, **send_kwargs)
        elif media_type == "voice":
            await context.bot.send_voice(voice=file_id, **send_kwargs)
        elif media_type == "video_note":
            await context.bot.send_video_note(video_note=file_id, **send_kwargs)
        elif media_type == "text":
            msg = file_id
            if text:
                msg += f"\n\n{text}"
            await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"🎉 Success!\n\n{text}", parse_mode="Markdown")

# List all codes
async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not codes:
        await update.message.reply_text("ℹ️ No codes created yet.", parse_mode="Markdown")
        return

    message = "📋 *Redeem Codes List:*\n\n"
    for code, info in codes.items():
        if isinstance(info["used_by"], list):  # multi-use
            used = len(info["used_by"])
            limit = info["limit"]
            message += f"• `{code}` — {used}/{limit} used\n"
        else:  # single-use
            status = "✅ Available" if info["used_by"] is None else f"❌ Redeemed by `{info['used_by']}`"
            message += f"• `{code}` — {status}\n"
    await update.message.reply_text(message, parse_mode="Markdown")

# Delete a code
async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage:\n`/deletecode <code>`", parse_mode="Markdown")
        return

    code = context.args[0].upper()
    if code not in codes:
        await update.message.reply_text("❌ Code Not Found", parse_mode="Markdown")
        return

    del codes[code]
    await update.message.reply_text(f"🗑️ Code `{code}` deleted.", parse_mode="Markdown")

# Flask app for hosting health check
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 Redeem Code Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="show_commands"))
    app.add_handler(CallbackQueryHandler(back_to_start_callback, pattern="back_to_start"))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("generate_multi", generate_multi))
    app.add_handler(CommandHandler("generate_random", generate_random))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("deletecode", deletecode))

    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
