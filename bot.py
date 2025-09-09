# bot_with_termux_status_and_ping.py
import os
import random
import string
import logging
import time
from threading import Thread
from typing import Optional, Set

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
codes = {}  # your existing codes store (in-memory)
_start_time = time.time()

# Helper: check admin
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Force Join Check (async)
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            # present join button if not joined
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

# Code generator
def generate_random_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

# ---------- Telegram command handlers (same as your previous logic) ----------
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
        "<code>/ping</code> — Check bot latency and uptime"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]]
    )

    await query.edit_message_text(
        text=commands_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

async def back_to_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📜 Commands", callback_data="show_commands")]]
    )

    await query.edit_message_text(
        text=start_message_admin,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

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
            "⚠️ Usage:\n<code>/generate_multi &lt;code&gt; &lt;limit&gt; &lt;optional message&gt;</code>\n\n"
            "You can also reply to a message with this command to attach media.",
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

    await update.message.reply_text(
        f"✅ Multi-use Code Created!\n\nCode: <code>{code}</code>\nLimit: {limit}",
        parse_mode=ParseMode.HTML
    )

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

# Redeem command (single & multi-use)
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
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("💬 Chat with User", url=f"tg://user?id={user_id}")]]
            )
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

        if media_type == "photo":
            await context.bot.send_photo(photo=file_id, **send_kwargs)
        elif media_type == "video":
            await context.bot.send_video(video=file_id, **send_kwargs)
        elif media_type == "document":
            await context.bot.send_document(document=file_id, **send_kwargs)
        elif media_type == "audio":
            await context.bot.send_audio(audio=file_id, **send_kwargs)
        elif media_type == "voice":
            await context.bot.send_voice(voice= file_id, **send_kwargs)
        elif media_type == "video_note":
            await context.bot.send_video_note(video_note=file_id, **send_kwargs)
        elif media_type == "text":
            msg = file_id
            if text:
                msg += f"\n\n{text}"
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"🎉 Success!\n\n{text}", parse_mode=ParseMode.HTML)

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

# ---------- New: Ping command ----------
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Replies with round-trip latency and uptime.
    """
    try:
        start = time.perf_counter()
        # send a temporary message to measure round-trip
        sent = await update.message.reply_text("🏓 Pinging...")
        elapsed = (time.perf_counter() - start) * 1000  # ms
        uptime = format_uptime(time.time() - _start_time)
        await sent.edit_text(f"🏓 Pong!\nLatency: {elapsed:.0f} ms\nUptime: {uptime}")
    except Exception as e:
        logger.error(f"/ping failed: {e}")
        await update.message.reply_text("⚠️ Unable to measure ping right now.")

# ---------- Flask status page & endpoints ----------
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
    .btn{padding:8px 10px;border-radius:10px;background:transparent;border:1px solid rgba(255,255,255,0.04);color:var(--muted);font-size:13px;cursor:pointer}
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
          <button class="btn" id="openBtn">Open Bot</button>
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
          <div class="stat"><b id="chan">—</b>Force Join Channel</div>
        </div>
      </div>
    </div>
  </div>

<script>
  const lines_template = [
    'booting termux-emulator...\\n',
    'loading modules: telegram-core, flask-host\\n',
    'checking force-join channel: {chan}\\n',
    'verifying token... OK\\n',
    'starting webhook / polling... OK\\n',
    'initializing redeem subsystem...\\n',
    'scanning codes database... {codes_count} codes found\\n',
    'ready. welcome to {bot_name}\\n'
  ];

  // fetch status and start animation
  async function fetchAndStart() {
    try {
      const res = await fetch('/status');
      const json = await res.json();
      const lines = lines_template.map(l => l.replace('{chan}', json.force_channel).replace('{bot_name}', json.bot_name).replace('{codes_count}', json.codes_count));
      startTypewriter(lines, json);
    } catch (e) {
      // fallback static lines
      startTypewriter(['failed to fetch /status\\n', 'running with fallback values\\n']);
    }
  }

  function startTypewriter(lines, status) {
    const out = document.getElementById('terminalLines');
    const bar = document.getElementById('bar');
    const pct = document.getElementById('percent');
    const ptext = document.getElementById('progressText');

    // fill stats if status provided
    if (status) {
      document.getElementById('uptime').innerText = status.uptime;
      document.getElementById('version').innerText = status.version;
      document.getElementById('users').innerText = status.active_users;
      document.getElementById('chan').innerText = status.force_channel;
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
          // small pause between lines
          setTimeout(typeNextLine, 220 + Math.random() * 220);
        }
      }, speed);
    }
    typeNextLine();
  }

  // Buttons (protected endpoints)
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
  document.getElementById('openBtn').addEventListener('click', async () => {
    const resp = await fetch('/open', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({secret: '{{WEB_SECRET}}'})
    });
    const j = await resp.json();
    alert(j.message || 'ok');
  });

  fetchAndStart();
</script>
</body>
</html>
"""

# Helper to compute uptime string
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

# Count active users from codes store (simple heuristic)
def compute_active_users() -> int:
    users: Set[int] = set()
    for info in codes.values():
        used_by = info.get("used_by")
        if isinstance(used_by, list):
            users.update(used_by)
        elif isinstance(used_by, int):
            users.add(used_by)
    return len(users)

@flask_app.route("/")
def home():
    # inject the secret into the template in a safe-ish way (render_template_string)
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
        "force_channel": FORCE_JOIN_CHANNEL,
        "bot_name": "Redeem Code Bot",
        "codes_count": len(codes)
    })

# Protected endpoints (placeholders)
def _check_secret(req_json):
    if not WEB_SECRET:
        return False
    return req_json.get("secret") == WEB_SECRET

@flask_app.route("/restart", methods=["POST"])
def http_restart():
    data = request.get_json(silent=True) or {}
    if not _check_secret(data):
        return jsonify({"ok": False, "message": "unauthorized"}), 401
    # PLACEHOLDER: implement your restart logic here if you want
    logger.info("Received /restart via HTTP - secret validated (no restart performed, placeholder).")
    return jsonify({"ok": True, "message": "restart endpoint received (placeholder)."}), 200

@flask_app.route("/open", methods=["POST"])
def http_open():
    data = request.get_json(silent=True) or {}
    if not _check_secret(data):
        return jsonify({"ok": False, "message": "unauthorized"}), 401
    # PLACEHOLDER: implement logic to "open" the bot/admin panel
    logger.info("Received /open via HTTP - secret validated (placeholder).")
    return jsonify({"ok": True, "message": "open endpoint received (placeholder)."}), 200

def run_flask():
    port = int(os.getenv("PORT", "5000"))
    # Bind to 0.0.0.0 for Render
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
    app.add_handler(CommandHandler("ping", ping))  # <-- Ping command added

    Thread(target=run_flask, daemon=True).start()

    logger.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
