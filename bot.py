import os
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import BadRequest

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL", "@botsproupdates")

if not BOT_TOKEN or ADMIN_ID == 0:
    raise ValueError("Please set BOT_TOKEN and ADMIN_ID environment variables!")

codes = {}

async def is_user_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, update.effective_user.id)
        return member.status in ("member", "administrator", "creator")
    except BadRequest:
        return False

async def force_join_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user.id == ADMIN_ID:
        return True
    joined = await is_user_member(update, context)
    if not joined:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👉 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.strip('@')}")]]
        )
        await update.message.reply_text(
            "🚨 You must join the channel to use this bot.",
            reply_markup=keyboard,
        )
    return joined

start_message_user = (
    "👋 *Welcome to the Redeem Code Bot!*\n\n"
    "Use `/redeem <code>` to redeem your code.\n\n"
    "Enjoy! 🤍"
)

start_message_admin = (
    "👋 *Welcome Admin!*\n\n"
    "Use `/redeem <code>` to redeem your code.\n"
    "Use `/generate <code> <custom message>` to create redeem codes."
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
        await update.message.reply_text("❌ You are not authorized.", parse_mode="Markdown")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /generate <code> <custom message>", parse_mode="Markdown")
        return
    code = context.args[0].upper()
    message = " ".join(context.args[1:])
    if code in codes:
        await update.message.reply_text("⚠️ Code already exists.", parse_mode="Markdown")
        return
    codes[code] = {"text": message, "used_by": None}
    await update.message.reply_text(f"✅ Code `{code}` created!", parse_mode="Markdown")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_check(update, context):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /redeem <code>", parse_mode="Markdown")
        return
    code = context.args[0].upper()
    user_id = update.effective_user.id
    if code not in codes:
        await update.message.reply_text("❌ Invalid code.", parse_mode="Markdown")
        return
    if codes[code]["used_by"] is not None:
        await update.message.reply_text("❌ Code already redeemed.", parse_mode="Markdown")
        return
    codes[code]["used_by"] = user_id
    await update.message.reply_text(f"🎉 Success!\n\n{codes[code]['text']}", parse_mode="Markdown")

# Flask health check
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Redeem Code Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("redeem", redeem))

    Thread(target=run_flask).start()

    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
