import os
import random
import string
import logging
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Forbidden, BadRequest
from telegram.constants import ParseMode

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load config
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")  # Example: @mychannel

if not BOT_TOKEN or not ADMIN_IDS or not FORCE_JOIN_CHANNEL:
    raise ValueError("Missing BOT_TOKEN, ADMIN_IDS, or FORCE_JOIN_CHANNEL environment variables!")

codes = {}

# Messages
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

# Helper
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# 🔹 Force Join
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
            "⚠️ <b>You must join our channel to use this bot.</b>",
            reply_markup=join_button,
            parse_mode=ParseMode.HTML
        )
        return False
    except Forbidden:
        await update.message.reply_text("⚠️ Bot is not admin in force join channel.")
        return False

# Code Generator
def generate_random_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

# ---------------- PANEL ---------------- #

async def show_panel_page(update_or_query, context, page=1):
    if page == 1:
        text = "⚙️ <b>Admin Control Panel (Page 1/2)</b>\n\nChoose an option below:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Generate Code", callback_data="panel_generate")],
            [InlineKeyboardButton("👥 Generate Multi-Use", callback_data="panel_multi")],
            [InlineKeyboardButton("📋 List Codes", callback_data="panel_list")],
            [InlineKeyboardButton("🗑️ Delete Code", callback_data="panel_delete")],
            [InlineKeyboardButton("🎲 Generate Random", callback_data="panel_random")],
            [InlineKeyboardButton("👉 Next Page", callback_data="panel_page2")],
        ])
    else:
        text = "⚙️ <b>Admin Control Panel (Page 2/2)</b>\n\nChoose an option below:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Stats", callback_data="panel_stats")],
            [InlineKeyboardButton("🔗 Force Join Info", callback_data="panel_forcejoin")],
            [InlineKeyboardButton("⬅️ Previous Page", callback_data="panel_page1")],
            [InlineKeyboardButton("❌ Close", callback_data="panel_close")],
        ])

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update_or_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)
        return
    await show_panel_page(update, context, page=1)

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "panel_generate":
        await query.edit_message_text("✍️ Send `/generate <code> <message>` to create a code.", parse_mode=ParseMode.HTML)
    elif query.data == "panel_multi":
        await query.edit_message_text(
            "👥 Send `/generate_multi <code> <limit> <optional message>`\n\nReply to a file/message to attach media.",
            parse_mode=ParseMode.HTML,
        )
    elif query.data == "panel_list":
        await listcodes(update, context)
    elif query.data == "panel_delete":
        await query.edit_message_text("🗑️ Send `/deletecode <code>` to delete a code.", parse_mode=ParseMode.HTML)
    elif query.data == "panel_random":
        await query.edit_message_text("🎲 Reply to a message with `/generate_random` to create a random code.", parse_mode=ParseMode.HTML)
    elif query.data == "panel_stats":
        total_codes = len(codes)
        redeemed = sum(
            1 if (isinstance(info.get("used_by"), int) and info["used_by"]) or
                 (isinstance(info.get("used_by"), list) and len(info["used_by"]) > 0)
            else 0
            for info in codes.values()
        )
        await query.edit_message_text(
            f"📊 <b>Bot Stats</b>\n\n• Total Codes: <b>{total_codes}</b>\n• Redeemed Codes: <b>{redeemed}</b>",
            parse_mode=ParseMode.HTML,
        )
    elif query.data == "panel_forcejoin":
        await query.edit_message_text(f"🔗 <b>Force Join Channel:</b> {FORCE_JOIN_CHANNEL}", parse_mode=ParseMode.HTML)
    elif query.data == "panel_page1":
        await show_panel_page(query, context, page=1)
    elif query.data == "panel_page2":
        await show_panel_page(query, context, page=2)
    elif query.data == "panel_close":
        await query.edit_message_text("❌ <b>Panel closed.</b>", parse_mode=ParseMode.HTML)

# ---------------- START ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Commands", callback_data="show_commands")],
            [InlineKeyboardButton("⚙️ Admin Panel", callback_data="open_panel")],
        ])
        await update.message.reply_text(start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update.message.reply_text(start_message_user, parse_mode=ParseMode.HTML)

async def show_commands_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    commands_text = (
        "🛠 <b>Admin Commands:</b>\n\n"
        "<code>/generate <code> <message></code> — One-time\n"
        "<code>/generate_multi <code> <limit> <message></code> — Multi-use\n"
        "<code>/generate_random <message></code> — Random one-time (reply)\n"
        "<code>/redeem <code></code> — Redeem a code\n"
        "<code>/listcodes</code> — List all codes\n"
        "<code>/deletecode <code></code> — Delete a code"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]])
    await query.edit_message_text(commands_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Commands", callback_data="show_commands")],
        [InlineKeyboardButton("⚙️ Admin Panel", callback_data="open_panel")],
    ])
    await query.edit_message_text(start_message_admin, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def panel_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_panel_page(query, context, page=1)

# ---------------- COMMANDS ---------------- #

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)

    if len(context.args) < 2:
        return await update.message.reply_text("⚠️ Usage:\n<code>/generate <code> <message></code>", parse_mode=ParseMode.HTML)

    code = context.args[0].upper()
    custom_message = " ".join(context.args[1:])
    if code in codes:
        return await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML)

    codes[code] = {"text": custom_message, "used_by": None, "media": None, "created_by": update.effective_user.id}
    await update.message.reply_text(f"✅ Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

async def generate_multi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)

    if len(context.args) < 2:
        return await update.message.reply_text("⚠️ Usage:\n<code>/generate_multi <code> <limit> <message></code>", parse_mode=ParseMode.HTML)

    code = context.args[0].upper()
    try:
        limit = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("⚠️ Limit must be a number", parse_mode=ParseMode.HTML)

    custom_message = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    if code in codes:
        return await update.message.reply_text("⚠️ Duplicate Code!", parse_mode=ParseMode.HTML)

    codes[code] = {"text": custom_message, "used_by": [], "limit": limit, "media": None, "created_by": update.effective_user.id}
    await update.message.reply_text(f"✅ Multi-use Code Created!\n\nCode: <code>{code}</code>\nLimit: {limit}", parse_mode=ParseMode.HTML)

async def generate_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Unauthorized", parse_mode=ParseMode.HTML)

    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ Reply to a message with <code>/generate_random</code>", parse_mode=ParseMode.HTML)

    while True:
        code = generate_random_code()
        if code not in codes:
            break
    custom_message = " ".join(context.args) if context.args else ""
    codes[code] = {"text": custom_message, "used_by": None, "media": None, "created_by": update.effective_user.id}
    await update.message.reply_text(f"✅ Random Code Created!\n\nCode: <code>{code}</code>", parse_mode=ParseMode.HTML)

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    if len(context.args) != 1:
        return await update.message.reply_text("⚠️ Usage:\n<code>/redeem <code></code>", parse_mode=ParseMode.HTML)

    code = context.args[0].upper()
    user = update.effective_user
    user_id = user.id
    if code not in codes:
        return await update.message.reply_text("❌ Invalid Code", parse_mode=ParseMode.HTML)

    # handle single-use / multi-use
    if isinstance(codes[code]["used_by"], list):
        if user_id in codes[code]["used_by"]:
            return await update.message.reply_text("❌ You already redeemed this code!", parse_mode=ParseMode.HTML)
        if len(codes[code]["used_by"]) >= codes[code]["limit"]:
            return await update.message.reply_text("❌ Code redemption limit reached!", parse_mode=ParseMode.HTML)
        codes[code]["used_by"].append(user_id)
    else:
        if codes[code]["used_by"] is not None:
            return await update.message.reply_text("❌ Already Redeemed", parse_mode=ParseMode.HTML)
        codes[code]["used_by"] = user_id

    # Notify creator
    creator_id = codes[code].get("created_by")
    if creator_id:
        try:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Chat with User", url=f"tg://user?id={user_id}")]])
            await context.bot.send_message(
                chat_id=creator_id,
                text=f"🎉 <b>Code Redeemed!</b>\n\n• Code: <code>{code}</code>\n• User: <a href='tg://user?id={user_id}'>{user.full_name}</a>",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to notify creator {creator_id}: {e}")

    await update.message.reply_text(f"🎉 Success!\n\n{codes[code]['text']}", parse_mode=ParseMode.HTML)

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not codes:
        return await update.message.reply_text("ℹ️ No codes created yet.", parse_mode=ParseMode.HTML)

    message = "📋 <b>Redeem Codes List:</b>\n\n"
    for code, info in codes.items():
        if isinstance(info["used_by"], list):
            used = len(info["used_by"])
            limit = info["limit"]
            message += f"• <code>{code}</code> — {used}/{limit} used\n"
        else:
            status = "✅ Available" if info["used_by"] is None else f"❌ Redeemed"
            message += f"• <code>{code}</code> — {status}\n"
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def deletecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        return await update.message.reply_text("⚠️ Usage:\n<code>/deletecode <code></code>", parse_mode=ParseMode.HTML)

    code = context.args[0].upper()
    if code not in codes:
        return await update.message.reply_text("❌ Code Not Found", parse_mode=ParseMode.HTML)

    del codes[code]
    await update.message.reply_text(f"🗑️ Code <code>{code}</code> deleted.", parse_mode=ParseMode.HTML)

# ---------------- FLASK ---------------- #
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 Redeem Code Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Start + Panel
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="panel_"))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="show_commands"))
    app.add_handler(CallbackQueryHandler(back_to_start_callback, pattern="back_to_start"))
    app.add_handler(CallbackQueryHandler(panel_open_callback, pattern="open_panel"))

    # Commands
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
