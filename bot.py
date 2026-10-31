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
    compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    match = re.search(r"([A-Z]\d{8,11})", compact)
    if match:
        return match.group(1)
    return None

def extract_from_image(image_bytes: bytes) -> str | None:
    """Processes image across 4 rotation angles with contrast enhancement."""
    try:
        base_img = Image.open(io.BytesIO(image_bytes)).convert("L")
        base_img = ImageOps.autocontrast(base_img)
        base_img = ImageEnhance.Sharpness(base_img).enhance(2.0)

        for angle in [0, 90, 270, 180]:
            rotated = base_img.rotate(angle, expand=True)
            extracted_text = pytesseract.image_to_string(rotated, config="--psm 11")
            found = clean_and_extract_code(extracted_text)
            if found:
                return found
    except Exception as e:
        print(f"OCR Error: {e}")
    return None

# 3. Live DTDC Tracking Engine via TrackCourier.io
TRACKCOURIER_API_KEY = os.environ.get(
    "TRACKCOURIER_API_KEY",
    "tc_live_U4AOaSNeOqClGF-z1FB7laq6cvah_ynPA9TZxhpCzL0"
)

def fetch_dtdc_live_status(tracking_no: str) -> str:
    url = f"https://api.trackcourier.io/v1/track?courier=dtdc&tracking_number={tracking_no}"
    headers = {
        "X-API-Key": TRACKCOURIER_API_KEY
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return (
                f"📦 *Consignment No:* `{tracking_no}`\n\n"
                f"⚠️ *Tracking service error (Status {resp.status_code}).* Please try again shortly."
            )

        data = resp.json()
        if not data.get("success"):
            error_msg = data.get("message", "No tracking information found.")
            return (
                f"📦 *Consignment No:* `{tracking_no}`\n\n"
                f"ℹ️ *{error_msg}*"
            )

        pkg_data = data.get("data", {})
        status = pkg_data.get("status", "IN TRANSIT").upper()
        estimated_delivery = pkg_data.get("estimated_delivery")
        checkpoints = pkg_data.get("checkpoints", [])

        lines = [
            f"📦 *Consignment No:* `{tracking_no}`",
            f"📍 *Status:* **{status}**"
        ]

        if estimated_delivery:
            lines.append(f"🗓️ *Estimated Delivery:* {estimated_delivery}")

        if checkpoints:
            lines.append("\n🕒 *Recent Milestones:*")
            # Show up to last 4 checkpoints (newest first)
            for cp in reversed(checkpoints[-4:]):
                dt = cp.get("date") or cp.get("time") or ""
                desc = cp.get("status") or cp.get("activity") or "Update"
                loc = cp.get("location")
                loc_text = f" ({loc})" if loc else ""
                lines.append(f"• `{dt}`: {desc}{loc_text}")
        else:
            lines.append("\nℹ️ Tracking record initialized. Detailed milestones are pending.")

        return "\n".join(lines)

    except requests.exceptions.Timeout:
        return f"📦 *Consignment No:* `{tracking_no}`\n\n⏱️ Request timed out connecting to the courier network."
    except Exception as e:
        return f"📦 *Consignment No:* `{tracking_no}`\n\n⚠️ Error processing request: `{str(e)}`"

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

    # Reset any active webhook before starting polling to avoid 409 Conflict
    try:
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true", timeout=5)
    except Exception:
        pass

    # Start Flask keep-alive server
    web_thread = threading.Thread(target=run_flask)
    web_thread.daemon = True
    web_thread.start()

    # Build and launch bot
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is up and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()
