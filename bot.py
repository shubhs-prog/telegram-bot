import os
import json
import fitz
import img2pdf
from PIL import Image
from pdf2docx import Converter
from docx2pdf import convert as docx_to_pdf_convert
from pypdf import PdfWriter, PdfReader
from datetime import datetime, timedelta
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Your Telegram user ID
UPI_ID = os.getenv("UPI_ID", "yourname@upi")  # Your UPI ID

DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "outputs"
DB_FILE = "users.json"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

FREE_LIMIT = 3  # conversions per day
user_pdf_collection = {}


# ── Database helpers ──────────────────────────────────────────
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def get_user(user_id):
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"conversions": 0, "date": str(datetime.today().date()), "premium": False, "premium_until": ""}
        save_db(db)
    return db[uid], db

def reset_if_new_day(user_id):
    user, db = get_user(user_id)
    today = str(datetime.today().date())
    if user["date"] != today:
        user["conversions"] = 0
        user["date"] = today
        db[str(user_id)] = user
        save_db(db)
    return user

def is_premium(user_id):
    user, _ = get_user(user_id)
    if not user["premium"]:
        return False
    until = datetime.strptime(user["premium_until"], "%Y-%m-%d").date()
    return datetime.today().date() <= until

def can_convert(user_id):
    if is_premium(user_id):
        return True
    user = reset_if_new_day(user_id)
    return user["conversions"] < FREE_LIMIT

def increment_usage(user_id):
    if is_premium(user_id):
        return
    user, db = get_user(user_id)
    user["conversions"] += 1
    db[str(user_id)] = user
    save_db(db)

def activate_premium(user_id):
    user, db = get_user(user_id)
    until = datetime.today().date() + timedelta(days=30)
    user["premium"] = True
    user["premium_until"] = str(until)
    db[str(user_id)] = user
    save_db(db)


# ── Commands ──────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = reset_if_new_day(user_id)
    remaining = max(0, FREE_LIMIT - user["conversions"])
    premium = is_premium(user_id)

    status = "⭐ Premium user" if premium else f"🆓 Free user ({remaining}/{FREE_LIMIT} conversions left today)"

    await update.message.reply_text(
        f"👋 Welcome to File Converter Bot!\n\n"
        f"Status: {status}\n\n"
        f"📌 What I can do:\n"
        f"🖼 Image → PDF\n"
        f"📄 PDF → Images\n"
        f"📝 Word (DOCX) → PDF\n"
        f"📄 PDF → Word\n"
        f"🗜 Image Compression\n"
        f"📎 PDF Merger\n\n"
        f"Commands:\n"
        f"/premium - Upgrade for ₹49/month\n"
        f"/status - Check your usage\n"
        f"/merge - Start PDF merge\n"
        f"/doMerge - Finish merging\n"
        f"/compress - Compress next image\n"
        f"/cancel - Cancel operation"
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = reset_if_new_day(user_id)
    premium = is_premium(user_id)

    if premium:
        until = user["premium_until"]
        msg = f"⭐ You are a Premium user!\nValid until: {until}"
    else:
        remaining = max(0, FREE_LIMIT - user["conversions"])
        msg = f"🆓 Free user\nConversions used today: {user['conversions']}/{FREE_LIMIT}\nRemaining: {remaining}\n\nUpgrade with /premium"

    await update.message.reply_text(msg)

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⭐ *Upgrade to Premium — ₹49/month*\n\n"
        f"✅ Unlimited conversions\n"
        f"✅ All file types supported\n"
        f"✅ Priority processing\n\n"
        f"*How to pay:*\n"
        f"1. Pay ₹49 to UPI: `{UPI_ID}`\n"
        f"2. Take a screenshot of payment\n"
        f"3. Send the screenshot here\n"
        f"4. Wait for activation (usually within 1 hour)\n\n"
        f"Your User ID: `{update.message.from_user.id}`\n"
        f"_(Include this in payment note)_",
        parse_mode="Markdown"
    )

async def compress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "compress"
    await update.message.reply_text("🗜 Send me an image to compress!")

async def merge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_pdf_collection[user_id] = []
    context.user_data["mode"] = "merge"
    await update.message.reply_text("📎 Merge mode ON! Send PDFs one by one, then /doMerge")

async def do_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    pdfs = user_pdf_collection.get(user_id, [])
    if len(pdfs) < 2:
        await update.message.reply_text("❌ Send at least 2 PDFs first!")
        return
    if not can_convert(user_id):
        await update.message.reply_text("❌ Daily limit reached! Upgrade with /premium")
        return
    await update.message.reply_text("⏳ Merging PDFs...")
    try:
        writer = PdfWriter()
        for pdf_path in pdfs:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)
        output_path = os.path.join(OUTPUT_DIR, f"merged_{user_id}.pdf")
        with open(output_path, "wb") as f:
            writer.write(f)
        await update.message.reply_document(document=open(output_path, "rb"), filename="merged.pdf", caption="✅ Merged!")
        increment_usage(user_id)
        user_pdf_collection[user_id] = []
        context.user_data["mode"] = None
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    user_pdf_collection[update.message.from_user.id] = []
    await update.message.reply_text("❌ Cancelled.")

async def to_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = context.user_data.get("pending_pdf")
    if not file_path:
        await update.message.reply_text("Send a PDF first!")
        return
    await convert_pdf_to_images(update, context, file_path)
    context.user_data["pending_pdf"] = None

async def to_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = context.user_data.get("pending_pdf")
    if not file_path:
        await update.message.reply_text("Send a PDF first!")
        return
    await convert_pdf_to_docx(update, file_path)
    context.user_data["pending_pdf"] = None


# ── Admin commands ────────────────────────────────────────────
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve <user_id>")
        return
    uid = context.args[0]
    activate_premium(uid)
    await update.message.reply_text(f"✅ User {uid} activated for 30 days!")
    try:
        await context.bot.send_message(int(uid), "🎉 Your Premium is now active for 30 days! Enjoy unlimited conversions.")
    except:
        pass

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    db = load_db()
    total = len(db)
    premium = sum(1 for u in db.values() if u.get("premium"))
    await update.message.reply_text(f"📊 Total users: {total}\n⭐ Premium: {premium}\n🆓 Free: {total - premium}")


# ── File handler ──────────────────────────────────────────────
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = message.from_user.id
    mode = context.user_data.get("mode")

    # Check if it's a payment screenshot (photo sent by free user in payment flow)
    if message.photo and context.user_data.get("awaiting_payment"):
        await handle_payment_screenshot(update, context)
        return

    # Check limit
    if not can_convert(user_id) and mode != "merge":
        await message.reply_text(
            "❌ You've used all 3 free conversions today!\n\n"
            "Upgrade to Premium for ₹49/month with /premium\n"
            "or wait until tomorrow for free conversions."
        )
        return

    if message.photo:
        file = await message.photo[-1].get_file()
        file_path = os.path.join(DOWNLOAD_DIR, f"{file.file_id}.jpg")
        await file.download_to_drive(file_path)
        if mode == "compress":
            await compress_image(update, file_path)
            context.user_data["mode"] = None
        else:
            await convert_image_to_pdf(update, file_path)
        increment_usage(user_id)
        return

    if not message.document:
        # Could be a payment screenshot
        await message.reply_text("Please send a file!")
        return

    doc = message.document
    mime = doc.mime_type or ""
    file_name = doc.file_name or "file"
    file = await doc.get_file()
    file_path = os.path.join(DOWNLOAD_DIR, file_name)
    await file.download_to_drive(file_path)
    ext = file_name.lower().split(".")[-1]

    # Payment screenshot as document
    if mime.startswith("image/") and context.user_data.get("awaiting_payment"):
        await handle_payment_screenshot(update, context)
        return

    if ext in ("jpg", "jpeg", "png") or mime in ("image/jpeg", "image/png"):
        if mode == "compress":
            await compress_image(update, file_path)
            context.user_data["mode"] = None
        else:
            await convert_image_to_pdf(update, file_path)
        increment_usage(user_id)

    elif ext == "pdf" or mime == "application/pdf":
        if mode == "merge":
            user_pdf_collection.setdefault(user_id, []).append(file_path)
            count = len(user_pdf_collection[user_id])
            await message.reply_text(f"✅ PDF #{count} added! Send more or /doMerge")
        else:
            context.user_data["pending_pdf"] = file_path
            await message.reply_text("📄 PDF received!\n\n/toImages - Convert to PNG\n/toWord - Convert to DOCX")

    elif ext == "docx":
        await convert_docx_to_pdf(update, file_path)
        increment_usage(user_id)
    else:
        await message.reply_text("❌ Unsupported file. Send JPG, PNG, PDF, or DOCX.")


async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "No username"
    await update.message.reply_text("✅ Payment screenshot received! We'll activate your premium within 1 hour.")
    context.user_data["awaiting_payment"] = False
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 New payment screenshot!\n"
            f"User ID: `{user_id}`\n"
            f"Username: @{username}\n\n"
            f"To approve: /approve {user_id}",
            parse_mode="Markdown"
        )


# ── Conversion functions ──────────────────────────────────────
async def convert_image_to_pdf(update, image_path):
    await update.message.reply_text("⏳ Converting...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.pdf")
        img = Image.open(image_path).convert("RGB")
        rgb_path = image_path + "_rgb.jpg"
        img.save(rgb_path, "JPEG")
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(rgb_path))
        await update.message.reply_document(document=open(output_path, "rb"), filename="converted.pdf", caption="✅ Done!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def convert_pdf_to_images(update, context, pdf_path):
    await update.message.reply_text("⏳ Converting...")
    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = os.path.join(OUTPUT_DIR, f"page_{i+1}.png")
            pix.save(img_path)
            await update.message.reply_document(document=open(img_path, "rb"), filename=f"page_{i+1}.png", caption=f"Page {i+1}")
        doc.close()
        increment_usage(update.message.from_user.id)
        await update.message.reply_text("✅ Done!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def convert_docx_to_pdf(update, docx_path):
    await update.message.reply_text("⏳ Converting...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.pdf")
        docx_to_pdf_convert(docx_path, output_path)
        await update.message.reply_document(document=open(output_path, "rb"), filename="converted.pdf", caption="✅ Done!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def convert_pdf_to_docx(update, pdf_path):
    await update.message.reply_text("⏳ Converting...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.docx")
        cv = Converter(pdf_path)
        cv.convert(output_path)
        cv.close()
        await update.message.reply_document(document=open(output_path, "rb"), filename="converted.docx", caption="✅ Done!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def compress_image(update, image_path):
    await update.message.reply_text("⏳ Compressing...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "compressed.jpg")
        img = Image.open(image_path).convert("RGB")
        img.save(output_path, "JPEG", quality=40, optimize=True)
        orig = os.path.getsize(image_path) / 1024
        comp = os.path.getsize(output_path) / 1024
        await update.message.reply_document(document=open(output_path, "rb"), filename="compressed.jpg",
            caption=f"✅ Compressed!\n📦 Original: {orig:.1f} KB\n📉 Compressed: {comp:.1f} KB")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ── Main ──────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("compress", compress_cmd))
    app.add_handler(CommandHandler("merge", merge_cmd))
    app.add_handler(CommandHandler("doMerge", do_merge))
    app.add_handler(CommandHandler("toImages", to_images))
    app.add_handler(CommandHandler("toWord", to_word))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
