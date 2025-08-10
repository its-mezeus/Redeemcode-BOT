import os
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import BadRequest

# Load config from environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL", "@botsproupdates")

if not BOT_TOKEN or ADMIN_ID == 0:
    raise ValueError("Missing BOT_TOKEN or ADMIN_ID environment variables!")

codes = {}

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, update.effective_user.id)
        return member.status in ["member", "administrator", "creator"]
    except BadRequest:
        return False

async def force_join_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user.id == ADMIN_ID:
        return True

    joined = await is_user_member(update, context)
    if not joined:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👉 Join Our Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.strip('@')}")]]
        )
        await update.message.reply_text(
            "🚨 *Access Denied*\n\n"
            "You must join our official channel to use this bot.\n"
            "Tap the button below to join, then try again.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    return joined

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
    "`/generate <code> <custom message>`"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_check(update, context):
        return

    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(start_message_admin, parse_mode="Markdown")
    else:
        await update.message.reply_text(start_message_user, parse_mode="Markdown")

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_check(update, context):
        return
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

    codes[code] = {"text": custom_message, "used_by": None}
    await update.message.reply_text(
        f"✅ *Code Created Successfully!*\n\nCode: `{code}`\nMessage: {custom_message}",
        parse_mode="Markdown"
    )

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_check(update, context):
        return
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
    await update.message.reply_text(
        f"🎉 *Success!*\n\n{codes[code]['text']}",
        parse_mode="Markdown"
    )

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_check(update, context):
        return
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
    if not await force_join_check(update, context):
        return
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
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("deletecode", deletecode))

    # Run Flask app in background thread
    Thread(target=run_flask).start()

    print("Bot is running...")
    loop = asyncio.get_event_loop()
    loop.create_task(app.run_polling())
    loop.run_forever()

if __name__ == "__main__":
    main()
