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
MENU, PHONE, TRIP, SUPPORT = range(4)

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
# ASOSIY MENYU
# ============================================================

def main_menu_keyboard():
    keyboard = [
        [
            KeyboardButton("🚕 Taksi buyurtma qilish")
        ],
        [
            KeyboardButton("📞 Qo'llab-quvvatlash")
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "🏠 ASOSIY MENYU\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu_keyboard()
    )

    return MENU


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    context.user_data.clear()

    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🚕 Surxon–Toshkent taksi xizmatiga xush kelibsiz.\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu_keyboard()
    )

    return MENU


# ============================================================
# TAKSI BUYURTMASINI BOSHLASH
# ============================================================

async def start_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            KeyboardButton(
                "📱 Telefon raqamimni yuborish",
                request_contact=True
            )
        ],
        [
            KeyboardButton("⬅️ Asosiy menyu")
        ]
    ]

    markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        "🚕 TAKSI BUYURTMASI\n\n"
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

    # Asosiy menyuga qaytish
    if message.text == "⬅️ Asosiy menyu":
        return await show_main_menu(update, context)

    if not message.contact:
        await message.reply_text(
            "❗ Iltimos, pastdagi tugma orqali "
            "o'zingizning telefon raqamingizni yuboring."
        )
        return PHONE

    contact = message.contact

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
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("⬅️ Asosiy menyu")]],
            resize_keyboard=True
        )
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

    if message.text == "⬅️ Asosiy menyu":
        return await show_main_menu(update, context)

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

    order_id = save_order(
        user_id=user.id,
        full_name=full_name,
        username=username,
        phone=phone,
        trip=trip,
    )

    await message.reply_text(
        "🙏 Buyurtmangiz uchun tashakkur!\n\n"
        "🚕 Haydovchilarimiz tez orada sizga "
        "aloqaga chiqishadi.\n\n"
        "📞 Iltimos, telefoningizni kuzatib turing.",
        reply_markup=main_menu_keyboard()
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

    return MENU


# ============================================================
# QO'LLAB-QUVVATLASHNI BOSHLASH
# ============================================================

async def start_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    keyboard = [
        [
            KeyboardButton("⬅️ Asosiy menyu")
        ]
    ]

    markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "📞 QO'LLAB-QUVVATLASH\n\n"
        "Savol, taklif yoki muammoingiz bo'lsa, "
        "xabarni shu yerga yozing.\n\n"
        "👨‍💼 Operatorimiz xabaringizni ko'rib chiqib, "
        "siz bilan bog'lanadi.\n\n"
        "✏️ Xabaringizni yozing:",
        reply_markup=markup
    )

    return SUPPORT


# ============================================================
# QO'LLAB-QUVVATLASH XABARINI QABUL QILISH
# ============================================================

async def receive_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    if message.text == "⬅️ Asosiy menyu":
        return await show_main_menu(update, context)

    if not message.text:
        await message.reply_text(
            "❗ Iltimos, xabaringizni matn ko'rinishida yuboring."
        )
        return SUPPORT

    full_name = user.full_name or "Noma'lum"

    username = (
        f"@{user.username}"
        if user.username
        else "Username yo'q"
    )

    support_message = (
        "📞 QO'LLAB-QUVVATLASH XABARI\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Mijoz: {full_name}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "💬 MIJOZ XABARI:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{message.text}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "↩️ Javob berish uchun ushbu xabarga "
        "Reply qiling."
    )

    admins = get_admins()

    if not admins:
        await message.reply_text(
            "⚠️ Hozircha operator mavjud emas.\n\n"
            "Iltimos, keyinroq qayta urinib ko'ring.",
            reply_markup=main_menu_keyboard()
        )
        return MENU

    sent_count = 0

    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=support_message
            )

            sent_count += 1

        except Exception as error:
            logger.error(
                "Support xabari admin %s ga yuborilmadi: %s",
                admin_id,
                error
            )

    if sent_count > 0:
        await message.reply_text(
            "✅ Xabaringiz operatorga yuborildi.\n\n"
            "📞 Operatorimiz tez orada siz bilan bog'lanadi.",
            reply_markup=main_menu_keyboard()
        )
    else:
        await message.reply_text(
            "⚠️ Xabaringizni operatorga yuborishda "
            "xatolik yuz berdi.\n\n"
            "Iltimos, keyinroq qayta urinib ko'ring.",
            reply_markup=main_menu_keyboard()
        )

    context.user_data.clear()

    return MENU


# ============================================================
# ADMINNING MIJOZGA JAVOBI
# ============================================================

async def admin_reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    if not message:
        return

    admin_user = update.effective_user

    if not admin_user:
        return

    if not is_admin(admin_user.id):
        return

    if not message.reply_to_message:
        return

    replied_text = message.reply_to_message.text or ""

    marker = "🆔 Telegram ID:"

    if marker not in replied_text:
        return

    try:
        after_marker = replied_text.split(
            marker,
            1
        )[1]

        client_id_text = after_marker.split(
            "\n",
            1
        )[0].strip()

        client_id = int(client_id_text)

    except (ValueError, IndexError):
        await message.reply_text(
            "❌ Mijoz Telegram ID sini aniqlab bo'lmadi."
        )
        return

    if not message.text:
        await message.reply_text(
            "❗ Hozircha faqat matnli javob yuborish mumkin."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=client_id,
            text=(
                "👨‍💼 OPERATOR JAVOBI\n\n"
                f"{message.text}"
            )
        )

        await message.reply_text(
            "✅ Javob mijozga yuborildi."
        )

    except Exception as error:
        logger.error(
            "Mijoz %s ga admin javobi yuborilmadi: %s",
            client_id,
            error
        )

        await message.reply_text(
            "❌ Javob yuborilmadi.\n\n"
            "Mijoz botni hali ishga tushirmagan "
            "bo'lishi mumkin yoki Telegram xatoligi yuz berdi."
        )


# ============================================================
# /CANCEL
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Jarayon bekor qilindi.\n\n"
        "🏠 Asosiy menyu:",
        reply_markup=main_menu_keyboard()
    )

    return MENU


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
        await 
