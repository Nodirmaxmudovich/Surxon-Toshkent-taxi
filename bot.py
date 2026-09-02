import os
import sqlite3
import logging
import threading
from datetime import datetime
from flask import Flask

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

# ============================================================
# SOZLAMALAR
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")

PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "taxi_bot.db"

# Suhbat bosqichlari
PHONE, TRIP = range(2)

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. Render Environment Variables "
        "bo'limiga BOT_TOKEN kiriting."
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("surxon_toshkent_taxi")


# ============================================================
# FLASK - RENDER PORT UCHUN
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Surxon-Toshkent Taxi Bot ishlayapti."


@app.route("/health")
def health():
    return "OK"


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# DATABASE
# ============================================================

db_lock = threading.Lock()


def get_connection():
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                full_name TEXT,
                username TEXT,
                phone TEXT NOT NULL,
                trip TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        connection.commit()
        connection.close()

    # Render Environment Variables ichidagi
    # boshlang'ich adminlarni bazaga qo'shamiz.
    if ADMIN_IDS.strip():
        for admin_id in ADMIN_IDS.split(","):
            admin_id = admin_id.strip()

            if admin_id.isdigit():
                add_admin(int(admin_id))


def add_admin(user_id: int):
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO admins
            (user_id, added_at)
            VALUES (?, ?)
        """, (
            user_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        connection.commit()
        connection.close()


def remove_admin(user_id: int):
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (user_id,)
        )

        connection.commit()
        connection.close()


def is_admin(user_id: int) -> bool:
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT user_id FROM admins WHERE user_id = ?",
            (user_id,)
        )

        result = cursor.fetchone()
        connection.close()

        return result is not None


def get_admins():
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT user_id FROM admins ORDER BY added_at"
        )

        rows = cursor.fetchall()
        connection.close()

        return [row["user_id"] for row in rows]


def save_order(
    user_id: int,
    full_name: str,
    username: str,
    phone: str,
    trip: str,
):
    with db_lock:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO orders
            (
                user_id,
                full_name,
                username,
                phone,
                trip,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            full_name,
            username,
            phone,
            trip,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        order_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return order_id


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    user = update.effective_user

    keyboard = [
        [
            KeyboardButton(
                "📱 Telefon raqamimni yuborish",
                request_contact=True
            )
        ]
    ]

    markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🚕 Surxon–Toshkent taksi xizmatiga xush kelibsiz.\n\n"
        "Buyurtma berish uchun telefon raqamingizni "
        "yuboring.",
        reply_markup=markup
    )

    return PHONE


# ============================================================
# TELEFON RAQAMINI QABUL QILISH
# ============================================================

async def receive_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    if not message.contact:
        await message.reply_text(
            "❗ Iltimos, pastdagi tugma orqali "
            "o'zingizning telefon raqamingizni yuboring."
        )
        return PHONE

    contact = message.contact

    # Telegram kontaktni user_id bilan yuborgan bo'lsa,
    # boshqa odamning kontaktini qabul qilmaymiz.
    if contact.user_id is not None:
        if contact.user_id != user.id:
            await message.reply_text(
                "❗ Iltimos, o'zingizning telefon "
                "raqamingizni yuboring."
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
        "⏰ Soat 07:00\n\n"
        "Yoki barchasini bitta xabarda yozishingiz mumkin.\n\n"
        "✏️ Qayerdan, qayerga va qachon "
        "borishingizni o'zingiz yozing.",
        reply_markup=ReplyKeyboardRemove()
    )

    return TRIP


# ============================================================
# SAFAR MA'LUMOTINI QABUL QILISH
# ============================================================

async def receive_trip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    trip = message.text.strip()

    if not trip:
        await message.reply_text(
            "❗ Iltimos, qayerdan, qayerga va qachon "
            "borishingizni yozing."
        )
        return TRIP

    phone = context.user_data.get("phone")

    if not phone:
        await message.reply_text(
            "❗ Telefon raqamingiz topilmadi.\n\n"
            "Iltimos, /start tugmasini bosib "
            "buyurtmani qaytadan boshlang."
        )

        context.user_data.clear()
        return ConversationHandler.END

    full_name = user.full_name or "Noma'lum"
    username = (
        f"@{user.username}"
        if user.username
        else "Username yo'q"
    )

    # Buyurtmani bazaga saqlash
    order_id = save_order(
        user_id=user.id,
        full_name=full_name,
        username=username,
        phone=phone,
        trip=trip,
    )

    # ========================================================
    # MIJOZGA AVTOMATIK JAVOB
    # ========================================================

    await message.reply_text(
        "🙏 Buyurtmangiz uchun tashakkur!\n\n"
        "🚕 Haydovchilarimiz tez orada sizga "
        "aloqaga chiqishadi.\n\n"
        "📞 Iltimos, telefoningizni kuzatib turing.",
        reply_markup=ReplyKeyboardRemove()
    )

    # ========================================================
    # ADMINLARGA BUYURTMA
    # ========================================================

    admin_message = (
        "🚕 YANGI TAKSI BUYURTMASI\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Buyurtma: #{order_id}\n\n"
        f"👤 Mijoz: {full_name}\n"
        f"📱 Telefon: {phone}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "📍 SAFAR MA'LUMOTI:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{trip}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕐 Buyurtma vaqti: "
        f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )

    admins = get_admins()

    if not admins:
        logger.warning(
            "Adminlar ro'yxati bo'sh. Buyurtma #%s "
            "hech kimga yuborilmadi.",
            order_id
        )

    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message
            )

        except Exception as error:
            logger.error(
                "Admin %s ga buyurtma #%s yuborilmadi: %s",
                admin_id,
                order_id,
                error
            )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# /CANCEL
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Buyurtma bekor qilindi.\n\n"
        "Yangi buyurtma berish uchun /start ni bosing.",
        reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


# ============================================================
# /MYID
# ============================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🆔 Sizning Telegram ID raqamingiz:\n\n"
        f"{update.effective_user.id}"
    )


# ============================================================
# /ADDADMIN
# ============================================================

async def add_admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Bu buyruq faqat adminlar uchun."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n\n"
            "/addadmin TELEGRAM_ID\n\n"
            "Masalan:\n"
            "/addadmin 123456789"
        )
        return

    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Telegram ID faqat raqamlardan "
            "iborat bo'lishi kerak."
        )
        return

    if is_admin(new_admin_id):
        await update.message.reply_text(
            "ℹ️ Bu foydalanuvchi allaqachon admin."
        )
        return

    add_admin(new_admin_id)

    await update.message.reply_text(
        "✅ Yangi admin qo'shildi.\n\n"
        f"🆔 Telegram ID: {new_admin_id}"
    )


# ============================================================
# /DELADMIN
# ============================================================

async def delete_admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Bu buyruq faqat adminlar uchun."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n\n"
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

    # O'zini o'chirishga yo'l qo'ymaymiz
    if remove_id == user_id:
        await update.message.reply_text(
            "❌ O'zingizni adminlar ro'yxatidan "
            "o'chira olmaysiz."
        )
        return

    if not is_admin(remove_id):
        await update.message.reply_text(
            "ℹ️ Bu ID adminlar ro'yxatida yo'q."
        )
        return

    remove_admin(remove_id)

    await update.message.reply_text(
        "✅ Admin o'chirildi.\n\n"
        f"🆔 Telegram ID: {remove_id}"
    )


# ============================================================
# /ADMINS
# ============================================================

async def admins_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Bu buyruq faqat adminlar uchun."
        )
        return

    admins = get_admins()

    if not admins:
        await update.message.reply_text(
            "👮 Adminlar ro'yxati bo'sh."
        )
        return

    text = "👮 ADMINLAR RO'YXATI\n\n"

    for index, admin_id in enumerate(admins, start=1):
        text += f"{index}. {admin_id}\n"

    await update.message.reply_text(text)


# ============================================================
# /HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if is_admin(user_id):
        await update.message.reply_text(
            "🚕 ADMIN YORDAM\n\n"
            "/start — Buyurtma berish\n"
            "/myid — Telegram ID\n"
            "/admins — Adminlar ro'yxati\n"
            "/addadmin ID — Admin qo'shish\n"
            "/deladmin ID — Admin o'chirish\n"
            "/cancel — Jarayonni bekor qilish"
        )
    else:
        await update.message.reply_text(
            "🚕 TAKSI BUYURTMASI\n\n"
            "/start — Taksi buyurtma qilish\n"
            "/cancel — Buyurtmani bekor qilish"
        )


# ============================================================
# XATOLARNI USHLASH
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Botda xatolik yuz berdi:",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info("Database ishga tushmoqda...")
    init_database()

    logger.info("Web server ishga tushmoqda...")
    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )
    web_thread.start()

    logger.info("Telegram bot ishga tushmoqda...")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # BUYURTMA JARAYONI
    # ========================================================

    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start)
        ],

        states={
            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    receive_phone
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_phone
                ),
            ],

            TRIP: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_trip
                ),
            ],
        },

        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],

        allow_reentry=True,
    )

    application.add_handler(conversation_handler)

    # ========================================================
    # BUYRUQLAR
    # ========================================================

    application.add_handler(
        CommandHandler("cancel", cancel)
    )

    application.add_handler(
        CommandHandler("myid", my_id)
    )

    application.add_handler(
        CommandHandler("addadmin", add_admin_command)
    )

    application.add_handler(
        CommandHandler("deladmin", delete_admin_command)
    )

    application.add_handler(
        CommandHandler("admins", admins_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_error_handler(error_handler)

    logger.info("🚕 SURXON-TOSHKENT TAXI BOT ISHGA TUSHDI!")

    # Telegram polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


# ============================================================
# ISHGA TUSHIRISH
# ============================================================

if __name__ == "__main__":
    main()
