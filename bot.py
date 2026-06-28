import os
import fitz  # PyMuPDF
import img2pdf
from PIL import Image
from pdf2docx import Converter
from docx2pdf import convert as docx_to_pdf_convert
from pypdf import PdfWriter, PdfReader
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = "8761418241:AAFYbkwT6wzOx9eig2DoHeFneaLnj1ipQ7A"  # Replace with your token
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "outputs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Store PDFs for merging per user
user_pdf_collection = {}


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to File Converter Bot!\n\n"
        "📌 What I can do:\n"
        "🖼 Image (JPG/PNG) → PDF\n"
        "📄 PDF → Images (PNG)\n"
        "📝 Word (DOCX) → PDF\n"
        "📄 PDF → Word (DOCX)\n"
        "🗜 Image Compression\n"
        "📎 PDF Merger (send multiple PDFs)\n\n"
        "Commands:\n"
        "/merge - Start collecting PDFs to merge\n"
        "/doMerge - Merge all collected PDFs\n"
        "/compress - Next image will be compressed\n"
        "/cancel - Cancel current operation\n\n"
        "Just send a file to get started!"
    )


# /compress command - sets mode
async def compress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "compress"
    await update.message.reply_text("🗜 Send me an image and I'll compress it!")


# /merge command - start collecting PDFs
async def merge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_pdf_collection[user_id] = []
    context.user_data["mode"] = "merge"
    await update.message.reply_text(
        "📎 Merge mode ON!\n"
        "Send me PDFs one by one, then send /doMerge when done."
    )


# /doMerge - merge all collected PDFs
async def do_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    pdfs = user_pdf_collection.get(user_id, [])

    if len(pdfs) < 2:
        await update.message.reply_text("❌ Send at least 2 PDFs first!")
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

        await update.message.reply_document(
            document=open(output_path, "rb"),
            filename="merged.pdf",
            caption="✅ Here's your merged PDF!"
        )
        user_pdf_collection[user_id] = []
        context.user_data["mode"] = None
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


# /cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    user_id = update.message.from_user.id
    user_pdf_collection[user_id] = []
    await update.message.reply_text("❌ Operation cancelled.")


# Handle files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    mode = context.user_data.get("mode")

    # --- PHOTO (compressed image by Telegram) ---
    if message.photo:
        file = await message.photo[-1].get_file()
        file_path = os.path.join(DOWNLOAD_DIR, f"{file.file_id}.jpg")
        await file.download_to_drive(file_path)

        if mode == "compress":
            await compress_image(update, file_path)
            context.user_data["mode"] = None
        else:
            await convert_image_to_pdf(update, file_path)
        return

    if not message.document:
        await message.reply_text("Please send a file!")
        return

    doc: Document = message.document
    mime = doc.mime_type or ""
    file_name = doc.file_name or "file"
    file = await doc.get_file()
    file_path = os.path.join(DOWNLOAD_DIR, file_name)
    await file.download_to_drive(file_path)

    ext = file_name.lower().split(".")[-1]

    # --- IMAGE FILE ---
    if ext in ("jpg", "jpeg", "png") or mime in ("image/jpeg", "image/png"):
        if mode == "compress":
            await compress_image(update, file_path)
            context.user_data["mode"] = None
        else:
            await convert_image_to_pdf(update, file_path)

    # --- PDF ---
    elif ext == "pdf" or mime == "application/pdf":
        if mode == "merge":
            user_id = message.from_user.id
            user_pdf_collection.setdefault(user_id, []).append(file_path)
            count = len(user_pdf_collection[user_id])
            await message.reply_text(f"✅ PDF #{count} added! Send more or /doMerge")
        else:
            await ask_pdf_action(update, context, file_path)

    # --- DOCX ---
    elif ext == "docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        await convert_docx_to_pdf(update, file_path)

    else:
        await message.reply_text("❌ Unsupported file. Send JPG, PNG, PDF, or DOCX.")


async def ask_pdf_action(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str):
    context.user_data["pending_pdf"] = file_path
    await update.message.reply_text(
        "📄 PDF received! What do you want?\n\n"
        "1️⃣ Send /toImages - Convert to PNG images\n"
        "2️⃣ Send /toWord - Convert to DOCX"
    )


# /toImages
async def to_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = context.user_data.get("pending_pdf")
    if not file_path:
        await update.message.reply_text("Send a PDF first!")
        return
    await convert_pdf_to_images(update, context, file_path)
    context.user_data["pending_pdf"] = None


# /toWord
async def to_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = context.user_data.get("pending_pdf")
    if not file_path:
        await update.message.reply_text("Send a PDF first!")
        return
    await convert_pdf_to_docx(update, file_path)
    context.user_data["pending_pdf"] = None


async def convert_image_to_pdf(update: Update, image_path: str):
    await update.message.reply_text("⏳ Converting image to PDF...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.pdf")
        img = Image.open(image_path).convert("RGB")
        rgb_path = image_path + "_rgb.jpg"
        img.save(rgb_path, "JPEG")
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(rgb_path))
        await update.message.reply_document(
            document=open(output_path, "rb"),
            filename="converted.pdf",
            caption="✅ Here's your PDF!"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def convert_pdf_to_images(update: Update, context: ContextTypes.DEFAULT_TYPE, pdf_path: str):
    await update.message.reply_text("⏳ Converting PDF to images...")
    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = os.path.join(OUTPUT_DIR, f"page_{i+1}.png")
            pix.save(img_path)
            await update.message.reply_document(
                document=open(img_path, "rb"),
                filename=f"page_{i+1}.png",
                caption=f"📄 Page {i+1}"
            )
        doc.close()
        await update.message.reply_text("✅ Done!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def convert_docx_to_pdf(update: Update, docx_path: str):
    await update.message.reply_text("⏳ Converting Word to PDF...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.pdf")
        docx_to_pdf_convert(docx_path, output_path)
        await update.message.reply_document(
            document=open(output_path, "rb"),
            filename="converted.pdf",
            caption="✅ Here's your PDF!"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def convert_pdf_to_docx(update: Update, pdf_path: str):
    await update.message.reply_text("⏳ Converting PDF to Word...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "converted.docx")
        cv = Converter(pdf_path)
        cv.convert(output_path)
        cv.close()
        await update.message.reply_document(
            document=open(output_path, "rb"),
            filename="converted.docx",
            caption="✅ Here's your Word file!"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def compress_image(update: Update, image_path: str):
    await update.message.reply_text("⏳ Compressing image...")
    try:
        output_path = os.path.join(OUTPUT_DIR, "compressed.jpg")
        img = Image.open(image_path).convert("RGB")
        img.save(output_path, "JPEG", quality=40, optimize=True)

        original_size = os.path.getsize(image_path) / 1024
        compressed_size = os.path.getsize(output_path) / 1024

        await update.message.reply_document(
            document=open(output_path, "rb"),
            filename="compressed.jpg",
            caption=f"✅ Compressed!\n📦 Original: {original_size:.1f} KB\n📉 Compressed: {compressed_size:.1f} KB"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("compress", compress_cmd))
    app.add_handler(CommandHandler("merge", merge_cmd))
    app.add_handler(CommandHandler("doMerge", do_merge))
    app.add_handler(CommandHandler("toImages", to_images))
    app.add_handler(CommandHandler("toWord", to_word))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()