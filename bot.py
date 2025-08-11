import os
import asyncio
import random
import string
import logging
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load config from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN or ADMIN_ID == 0:
    raise ValueError("Missing BOT_TOKEN or ADMIN_ID environment variables!")

codes = {}

start_message_user = (
    "👋 *Welcome to the Redeem Code Bot!*\n\n"
    "Use the command below to redeem your code:\n\n"
    "`/redeem <code>`\n\n"
    "Enjoy! 🤍"
)

start_message_admin = (
    "👋 *Welcome to the Redeem Code Bot!*\n\n"
    "Use the command below to redeem your code:\n\n"
    "`/redeem <code>`\n\n"
    "If you are the admin, you can generate codes with:\n\n"
    "`/generate <code> <custom message>`\n"
    "Or reply to any message with `/generate_random <optional custom message>` to create a random code."
)

def generate_random_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(start_message_admin, parse_mode="Markdown")
    else:
        await update.message.reply_text(start_message_user, parse_mode="Markdown")

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ *Unauthorized*\nYou do not have permission to generate codes.",
            parse_mode="Markdown"
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Invalid Usage*\n\n"
            "Correct format:\n"
            "`/generate <code> <custom message>`",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].upper()
    custom_message = " ".join(context.args[1:])

    if code in codes:
        await update.message.reply_text(
            "⚠️ *Duplicate Code*\nThis code already exists.",
            parse_mode="Markdown"
        )
        return

    codes[code] = {"text": custom_message, "used_by": None, "media": None}
    await update.message.reply_text(
        f"✅ *Code Created Successfully!*\n\nCode: `{code}`\nMessage: {custom_message}",
        parse_mode="Markdown"
    )

async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ *Unauthorized*\nYou do not have permission to generate codes.",
            parse_mode="Markdown"
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ *Usage Error*\nReply to a message (text, photo, document, etc.) with:\n`/generate_random <optional custom message>`",
            parse_mode="Markdown"
        )
        return

    # Generate unique code
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
        await update.message.reply_text(
            "⚠️ Unsupported media type. Please reply to a text or supported media message.",
            parse_mode="Markdown"
        )
        return

    codes[code] = {
        "text": custom_message,
        "used_by": None,
        "media": {"type": media_type, "file_id": media}
    }

    await update.message.reply_text(
        f"✅ *Random Code Created!*\n\nCode: `{code}`\nMessage: {custom_message if custom_message else 'No extra message.'}",
        parse_mode="Markdown"
    )

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text(
            "⚠️ *Invalid Usage*\n\n"
            "Use this format:\n"
            "`/redeem <code>`",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].upper()
    user_id = update.effective_user.id

    if code not in codes:
        await update.message.reply_text(
            "❌ *Invalid Code*\nThe code you entered does not exist.",
            parse_mode="Markdown"
        )
        return

    if codes[code]["used_by"] is not None:
        await update.message.reply_text(
            "❌ *Already Redeemed*\nThis code has already been used.",
            parse_mode="Markdown"
        )
        return

    codes[code]["used_by"] = user_id

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
            await update.message.reply_text(
                f"🎉 *Success!*\n\n{text}",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"🎉 *Success!*\n\n{text}",
            parse_mode="Markdown"
        )

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not codes:
        await update.message.reply_text(
            "ℹ️ *No codes have been created yet.*",
            parse_mode="Markdown"
        )
        return

    message = "📋 *Redeem Codes List:*\n\n"
    for code, info in codes.items():
        status = "✅ Available" if info["used_by"] is None else f"❌ Redeemed by user `{info['used_by']}`"
        message += f"• `{code}` — {status}\n"
    await update.message.reply_text(message, parse_mode="Markdown")

async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text(
            "⚠️ *Invalid Usage*\n\n"
            "Use:\n"
            "`/deletecode <code>`",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].upper()

    if code not in codes:
        await update.message.reply_text(
            "❌ *Code Not Found*\nPlease check the code and try again.",
            parse_mode="Markdown"
        )
        return

    del codes[code]
    await update.message.reply_text(
        f"🗑️ *Code Deleted*\nCode `{code}` has been removed.",
        parse_mode="Markdown"
    )

# Flask app for hosting health check
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 Redeem Code Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("generate_random", generate_random))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("deletecode", deletecode))

    # Run Flask app in background thread
    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    asyncio.run(app.run_polling())

if __name__ == "__main__":
    main()
