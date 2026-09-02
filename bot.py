import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================
# SOZLAMALAR
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN Environment Variable topilmadi!")

DB_FILE = "taxi_bot.db"

PHONE, TRIP = range(2)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

def get_connection():
    return sqlite3.connect(DB_FILE)


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT,
            phone TEXT,
            trip TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_admin_to_db(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
        (user_id,)
    )

    conn.commit()
    conn.close()


def remove_admin_from_db(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM admins WHERE user_id = ?",
        (user_id,)
    )

    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id FROM admins WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()
    conn.close()

    return result is not None


def get_admins():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM admins")
    admins = [row[0] for row in cursor.fetchall()]

    conn.close()

    return admins


def save_order(user_id, full_name, phone, trip):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO orders
        (user_id, full_name, phone, trip, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        full_name,
        phone,
        trip,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    order_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return order_id


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    # Eski ma'lumotlarni tozalash
    context.user_data.clear()

    keyboard = [
        [
            KeyboardButton(
                "📱 Telefon raqamimni yuborish",
                request_contact=True
            )
        ]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🚕 Surxon–Toshkent taksi xizmatiga xush kelibsiz.\n\n"
        "Buyurtma berish uchun avval telefon raqamingizni yuboring.",
        reply_markup=reply_markup
    )

    return PHONE


# =========================
# TELEFON RAQAMINI QABUL QILISH
# =========================

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    message = update.message

    if not message.contact:
        await message.reply_text(
            "Iltimos, telefon raqamingizni pastdagi "
            "📱 tugma orqali yuboring."
        )
        return PHONE

    contact = message.contact

    # Boshqa odamning kontaktini yuborishni bloklash
    if contact.user_id and contact.user_id != user.id:
        await message.reply_text(
            "❗ Iltimos, o'zingizning telefon raqamingizni yuboring."
        )
        return PHONE

    phone = contact.phone_number

    context.user_data["phone"] = phone

    await message.reply_text(
        "✅ Telefon raqamingiz qabul qilindi.\n\n"
        "Endi safaringiz haqida ma'lumot yozing.\n\n"
        "Masalan:\n"
        "📍 Termizdan Toshkentga\n"
        "📅 5-sentabr\n"
        "⏰ Soat 07:00 da\n\n"
        "Yoki barchasini bitta xabarda yozishingiz mumkin.",
        reply_markup=ReplyKeyboardRemove()
    )

    return TRIP


# =========================
# SAFAR MA'LUMOTINI QABUL QILISH
# =========================

async def receive_trip(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    trip = update.message.text.strip()

    if not trip:
        await update.message.reply_text(
            "Iltimos, qayerdan, qayerga va qachon borishingizni yozing."
        )
        return TRIP

    phone = context.user_data.get("phone")

    if not phone:
        await update.message.reply_text(
            "Telefon raqamingiz topilmadi. Iltimos, /start buyrug'ini bosing."
        )
        return ConversationHandler.END

    full_name = user.full_name
    user_id = user.id

    # Buyurtmani bazaga saqlash
    order_id = save_order(
        user_id=user_id,
        full_name=full_name,
        phone=phone,
        trip=trip
    )

    # =========================
    # MIJOZGA JAVOB
    # =========================

    await update.message.reply_text(
        "🙏 Buyurtmangiz uchun tashakkur!\n\n"
        "🚕 Haydovchilarimiz tez orada siz bilan "
        "bog'lanishadi.\n\n"
        "📞 Telefoningizni kuzatib turing.",
        reply_markup=ReplyKeyboardRemove()
    )

    # =========================
    # ADMINLARGA XABAR
    # =========================

    admin_message = (
        "🚕 YANGI TAKSI BUYURTMASI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Buyurtma: #{order_id}\n"
        f"👤 Mijoz: {full_name}\n"
        f"📱 Telefon: {phone}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        "📍 SAFAR MA'LUMOTI:\n"
        f"{trip}\n\n"
        f"🕐 Buyurtma vaqti: "
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    admins = get_admins()

    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message
            )
        except Exception as e:
            logger.error(
                f"Admin {admin_id} ga xabar yuborilmadi: {e}"
            )

    context.user_data.clear()

    return ConversationHandler.END


# =========================
# CANCEL
# =========================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Buyurtma bekor qilindi.\n\n"
        "Yangi buyurtma berish uchun /start ni bosing.",
        reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


# =========================
# MY ID
# =========================

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        f"🆔 Sizning Telegram ID raqamingiz:\n\n"
        f"`{update.effective_user.id}`",
        parse_mode="Markdown"
    )


# =========================
# ADD ADMIN
# =========================

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Siz admin emassiz."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "/addadmin TELEGRAM_ID\n\n"
            "Masalan:\n"
            "/addadmin 123456789"
        )
        return

    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Telegram ID faqat raqamlardan iborat bo'lishi kerak."
        )
        return

    add_admin_to_db(new_admin_id)

    await update.message.reply_text(
        f"✅ Yangi admin qo'shildi.\n\n"
        f"🆔 Admin ID: {new_admin_id}"
    )


# =========================
# REMOVE ADMIN
# =========================

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Siz admin emassiz."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "/deladmin TELEGRAM_ID"
        )
        return

    try:
        remove_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Telegram ID noto'g'ri."
        )
        return

    # O'zini o'chirib yuborishning oldini olish
    if remove_id == user_id:
        await update.message.reply_text(
            "❌ O'zingizni adminlar ro'yxatidan o'chira olmaysiz."
        )
        return

    remove_admin_from_db(remove_id)

    await update.message.reply_text(
        f"✅ Admin o'chirildi.\n\n"
        f"🆔 ID: {remove_id}"
    )


# =========================
# ADMINLAR RO'YXATI
# =========================

async def admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Siz admin emassiz."
        )
        return

    admins = get_admins()

    if not admins:
        await update.message.reply_text(
            "Adminlar ro'yxati bo'sh."
        )
        return

    text = "👮 ADMINLAR RO'YXATI\n\n"

    for number, admin_id in enumerate(admins, start=1):
        text += f"{number}. `{admin_id}`\n"

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# =========================
# ERROR
# =========================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):

    logger.error(
        "Botda xatolik:",
        exc_info=context.error
    )


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

def main():

    init_database()

    # Environment orqali boshlang'ich adminlarni olish
    admin_ids = os.getenv("ADMIN_IDS", "")

    if admin_ids:
        for admin_id in admin_ids.split(","):
            admin_id = admin_id.strip()

            if admin_id.isdigit():
                add_admin_to_db(int(admin_id))

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Buyurtma berish jarayoni
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start)
        ],

        states={

            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    receive_phone
                )
            ],

            TRIP: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_trip
                )
            ],
        },

        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],

        allow_reentry=True
    )

    application.add_handler(conversation_handler)

    # Admin buyruqlari
    application.add_handler(
        CommandHandler("myid", my_id)
    )

    application.add_handler(
        CommandHandler("addadmin", add_admin)
    )

    application.add_handler(
        CommandHandler("deladmin", remove_admin)
    )

    application.add_handler(
        CommandHandler("admins", admins_list)
    )

    application.add_error_handler(error_handler)

    print("🚕 Surxon-Toshkent Taxi bot ishga tushdi!")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
