# Redeem Code Telegram Bot

A Telegram bot that allows the admin to generate custom redeem codes, which users can redeem for custom messages. Includes a force-join requirement for a specified channel.

---

## Features

- Admin can generate redeem codes with custom text messages.
- Users can redeem codes **only once**.
- Force users to join a Telegram channel before using the bot.
- Simple Flask web server included for hosting compatibility (e.g. on Render).
- Commands to list and delete redeem codes (admin only).
- All configuration via environment variables.

---

## Commands

### User Commands

- `/start`  
  Starts the bot and shows instructions.

- `/redeem <code>`  
  Redeem a code. Example: `/redeem ABC123`

### Admin Commands (only admin user ID)

- `/generate <code> <custom message>`  
  Create a new redeem code with a custom message.  
  Example: `/generate ABC123 You won a prize!`

- `/listcodes`  
  List all redeem codes and their statuses.

- `/deletecode <code>`  
  Delete an existing redeem code.  
  Example: `/deletecode ABC123`

---

## Setup & Deployment

### Requirements

- Python 3.10+
- `python-telegram-bot` v20.3
- `flask`

### Install dependencies

```bash
pip install python-telegram-bot==20.3 flask
