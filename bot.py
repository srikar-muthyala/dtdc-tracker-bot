import os
import io
import re
import asyncio
import threading
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

# 1. Lightweight Flask server to satisfy Render's free Web Service health checks
server = Flask(__name__)

@server.route("/")
def home():
    return "DTDC Telegram Bot is live and running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# 2. Tracking extractor logic
def extract_tracking_number(image_bytes: bytes) -> str | None:
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    extracted_text = pytesseract.image_to_string(img)
    compact_text = extracted_text.replace(" ", "").upper()

    # Match common DTDC consignment patterns (Letter + 8 to 10 digits)
    match = re.search(r"([A-Z]\d{8,10})", compact_text)
    if match:
        return match.group(1)
    return None

def get_tracking_message(tracking_no: str) -> str:
    portal_url = "https://www.dtdc.in/tracking.asp"
    swytch_url = "https://swytch.dtdc.com/track/"
    return (
        f"📦 *Tracking Number Found:*\n`{tracking_no}`\n\n"
        f"🔍 *Check Live Status:*\n"
        f"• [DTDC Official Portal]({portal_url})\n"
        f"• [DTDC Swytch Tracker]({swytch_url})\n\n"
        f"Select *AWB / Consignment* and paste: `{tracking_no}`"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me a photo of your DTDC barcode or shipping label, and I will extract the tracking code for you."
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    await update.message.reply_text("🔍 Scanning image for tracking code...")

    tracking_no = extract_tracking_number(bytes(image_bytes))
    if not tracking_no:
        await update.message.reply_text(
            "❌ Could not detect a valid DTDC tracking number.\n"
            "Please make sure the text under the barcode (e.g., B5001744194) is sharp, clear, and well-lit."
        )
        return

    msg = get_tracking_message(tracking_no)
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    # Start Flask in a background thread
    web_thread = threading.Thread(target=run_flask)
    web_thread.daemon = True
    web_thread.start()

    # Start Telegram polling
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Bot is up and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()