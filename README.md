# 🎁 Redeem Code Telegram Bot  

A Telegram bot that lets admins generate **one-time** and **multi-use redeem codes**.  
Users can redeem codes to receive text or media rewards — but only after joining required channels.  

---

## ✨ Features  

- 🔒 **Force Join** (supports multiple channels)  
- 🎫 **One-time codes** (`/generate`)  
- 🎟 **Multi-use codes with limits** (`/generate_multi`)  
- 🎲 **Random one-time codes** (with media support)  
- 📩 **Notify creator when a code is redeemed**  
- 📜 **List and delete codes**  
- 🎥 **Media support** (photo, video, document, audio, voice, text, etc.)  
- 🌐 **Flask health check** (for Render/Heroku uptime pings)  

---

## ⚙️ Setup  

### 1. Create a Bot  
- Talk to [@BotFather](https://t.me/BotFather)  
- Get your **Bot Token**  

### 2. Make Bot Admin in Channels  
- Add the bot to all channels you want as **force join**  
- Promote it to **Admin** (Read member info required)  

### 3. Environment Variables  
Set the following environment variables:  

| Variable | Example | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | `123456:ABC-xyz` | Your bot token from BotFather |
| `ADMIN_IDS` | `123456789,987654321` | Telegram user IDs of bot admins (comma separated) |
| `FORCE_JOIN_CHANNELS` | `@channel1,@channel2` | Required channels for force join (comma separated) |
| `PORT` | `5000` | (Optional) Port for Flask health check |

Example `.env` file:  
```env
BOT_TOKEN=123456:ABC-xyz
ADMIN_IDS=123456789,987654321
FORCE_JOIN_CHANNELS=@mychannel,@backupchannel
PORT=5000
