import os
import io
import re
import threading
import requests
from flask import Flask
from PIL import Image, ImageOps, ImageEnhance
import pytesseract

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 1. Flask keep-alive server for Render
server = Flask(__name__)

@server.route("/")
def home():
    return "DTDC Telegram Bot is live and tracking!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# 2. Pattern Matching
def clean_and_extract_code(text: str) -> str | None:
    # Match standard DTDC patterns: 1 letter followed by 8 to 11 digits
    compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    match = re.search(r"([A-Z]\d{8,11})", compact)
    if match:
        return match.group(1)
    return None

def extract_from_image(image_bytes: bytes) -> str | None:
    """Processes image across 4 rotation angles with contrast enhancement."""
    base_img = Image.open(io.BytesIO(image_bytes)).convert("L")
    base_img = ImageOps.autocontrast(base_img)
    base_img = ImageEnhance.Sharpness(base_img).enhance(2.0)

    # Test 0, 90, 180, 270 degrees in case photo was taken vertically/sideways
    for angle in [0, 90, 270, 180]:
        rotated = base_img.rotate(angle, expand=True)
        # psm 11 detects sparse text in no particular order
        extracted_text = pytesseract.image_to_string(rotated, config="--psm 11")
        found = clean_and_extract_code(extracted_text)
        if found:
            return found

    return None

# 3. Live DTDC Tracking Engine
def fetch_dtdc_live_status(tracking_no: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://swytch.dtdc.com/track/",
        "Origin": "https://swytch.dtdc.com"
    }

    portal_url = "https://www.dtdc.in/tracking.asp"
    swytch_url = "https://swytch.dtdc.com/track/"
    status_summary = None
    latest_event = None

    try:
        # Swytch public endpoint for AWB tracking
        api_url = f"https://swytch.dtdc.com/api/shipment/track/awb/{tracking_no}"
        resp = requests.get(api_url, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                # Retrieve top-level or checkpoint status
                status_summary = data.get("currentStatus") or data.get("status")
                history = data.get("trackingDetails") or data.get("events") or []
                if history and isinstance(history, list):
                    latest_event = history[-1].get("description") or history[-1].get("status")
    except Exception:
        pass

    if status_summary or latest_event:
        current = status_summary or latest_event
        return (
            f"📦 *Consignment No:* `{tracking_no}`\n"
            f"📍 *Current Status:* **{current}**\n\n"
            f"🔗 *Full Checkpoint Details:*\n"
            f"• [DTDC Official Portal]({portal_url})\n"
            f"• [DTDC Swytch Tracker]({swytch_url})"
        )
    else:
        return (
            f"📦 *Consignment No:* `{tracking_no}`\n\n"
            f"ℹ️ *No immediate live API response for this consignment ID.*\n\n"
            f"Check directly on the official tracking portals:\n"
            f"• [DTDC Official Portal]({portal_url})\n"
            f"• [DTDC Swytch Tracker]({swytch_url})\n\n"
            f"Select *AWB / Consignment* and enter: `{tracking_no}`"
        )

# 4. Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Send me either:\n"
        "• A **photo** of your DTDC barcode/shipping label (any orientation)\n"
        "• Or the **consignment number** directly in text (e.g. `B5001744194`)."
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    await update.message.reply_text("🔍 Analyzing label image...")

    tracking_no = extract_from_image(bytes(image_bytes))
    if not tracking_no:
        await update.message.reply_text(
            "❌ Could not detect the tracking number from this photo.\n\n"
            "Try sending a tighter crop of just the barcode area, or send the number as plain text."
        )
        return

    msg = fetch_dtdc_live_status(tracking_no)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    tracking_no = clean_and_extract_code(user_text)

    if not tracking_no:
        await update.message.reply_text(
            "❌ That doesn't look like a valid DTDC consignment number.\n"
            "Please check the digits and try again (e.g. `B5001744194`)."
        )
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)
    msg = fetch_dtdc_live_status(tracking_no)
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    web_thread = threading.Thread(target=run_flask)
    web_thread.daemon = True
    web_thread.start()

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is up and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()
