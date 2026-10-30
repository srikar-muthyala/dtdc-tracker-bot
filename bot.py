import os
import io
import re
import threading
import requests
from flask import Flask
from PIL import Image
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

# 1. Lightweight web server for Render health checks
server = Flask(__name__)

@server.route("/")
def home():
    return "DTDC Telegram Bot is live and tracking!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# 2. Text and Image Extraction
def clean_and_extract_code(text: str) -> str | None:
    """Detects DTDC consignment pattern (e.g. B5001744194)."""
    compact_text = text.replace(" ", "").upper()
    match = re.search(r"\b([A-Z]\d{8,10})\b", compact_text)
    if match:
        return match.group(1)
    return None

def extract_from_image(image_bytes: bytes) -> str | None:
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    extracted_text = pytesseract.image_to_string(img)
    return clean_and_extract_code(extracted_text)

# 3. Live Tracking Fetcher
def fetch_dtdc_live_status(tracking_no: str) -> str:
    """Attempts to query DTDC shipment data directly."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }
    
    status_summary = None
    try:
        # Standard DTDC public JSON tracking lookup
        url = f"https://track.dtdc.com/ct-tracking/customer/trackShipment?trackingNo={tracking_no}"
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                status_summary = (
                    data.get("currentStatus") 
                    or data.get("status") 
                    or data.get("shipmentStatus")
                )
    except Exception:
        status_summary = None

    portal_url = "https://www.dtdc.in/tracking.asp"
    swytch_url = "https://swytch.dtdc.com/track/"

    if status_summary:
        body = (
            f"📦 *Consignment No:* `{tracking_no}`\n"
            f"📍 *Current Status:* `{status_summary}`\n\n"
            f"🔗 *Full Checkpoint Details:*\n"
            f"• [DTDC Official Portal]({portal_url})\n"
            f"• [DTDC Swytch Tracker]({swytch_url})"
        )
    else:
        body = (
            f"📦 *Consignment No:* `{tracking_no}`\n\n"
            f"⚠️ *Live update not retrieved directly (portal session active).*\n\n"
            f"🔗 *Tap to view complete details:*\n"
            f"• [DTDC Official Portal]({portal_url})\n"
            f"• [DTDC Swytch Tracker]({swytch_url})\n\n"
            f"Select *AWB / Consignment* and paste: `{tracking_no}`"
        )
    return body

# 4. Telegram Event Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Send me either:\n"
        "• A **photo** of your DTDC barcode or shipping label\n"
        "• Or the **consignment code** directly in text (e.g. `B5001744194`).\n\n"
        "I will extract it and pull the latest status for you!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    await update.message.reply_text("🔍 Scanning image for tracking code...")

    tracking_no = extract_from_image(bytes(image_bytes))
    if not tracking_no:
        await update.message.reply_text(
            "❌ Could not detect a valid DTDC tracking number.\n"
            "Please ensure the number below the barcode is clearly visible, or send it as plain text."
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
            "DTDC tracking numbers usually begin with a letter followed by 8–10 digits (e.g. `B5001744194`)."
        )
        return

    await update.message.chat.send_action(action=ChatAction.TYPING)
    msg = fetch_dtdc_live_status(tracking_no)
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    # Run background Flask server
    web_thread = threading.Thread(target=run_flask)
    web_thread.daemon = True
    web_thread.start()

    # Telegram Polling
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is listening for text and photos...")
    app.run_polling()

if __name__ == "__main__":
    main()
