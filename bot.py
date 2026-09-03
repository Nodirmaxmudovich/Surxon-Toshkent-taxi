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

# Suhbat holatlari
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
# FLASK
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
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        # Adminlar
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)

        # Buyurtmalar
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

        # Support xabarlari
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                admin_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(admin_id, admin_message_id)
            )
        """)

        connection.commit()
        connection.close()

    # Environment Variables dagi adminlarni bazaga qo'shish
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
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))

        connection.commit()
        connection.close()


def remove_admin(user_id: int):

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (user_id,),
        )

        connection.commit()
        connection.close()


def is_admin(user_id: int) -> bool:

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT user_id FROM admins WHERE user_id = ?",
            (user_id,),
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
    user_id,
    full_name,
    username,
    phone,
    trip,
):

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO orders (
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
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))

        order_id = cursor.lastrowid

        connection.commit()
        connection.close()

        return order_id


def save_support_message(
    client_id,
    admin_id,
    admin_message_id,
):

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO support_messages (
                client_id,
                admin_id,
                admin_message_id,
                created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            client_id,
            admin_id,
            admin_message_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))

        connection.commit()
        connection.close()


def get_client_by_support_message(
    admin_id,
    admin_message_id,
):

    with db_lock:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT client_id
            FROM support_messages
            WHERE admin_id = ?
            AND admin_message_id = ?
        """, (
            admin_id,
            admin_message_id,
        ))

        row = cursor.fetchone()

        connection.close()

        if row:
            return row["client_id"]

        return None


# ============================================================
# MENYU
# ============================================================

def main_menu_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "🚕 Taksi buyurtma qilish"
                )
            ],
            [
                KeyboardButton(
                    "📞 Qo'llab-quvvatlash"
                )
            ],
        ],
        resize_keyboard=True,
    )


def back_menu_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "⬅️ Asosiy menyu"
                )
            ]
        ],
        resize_keyboard=True,
    )


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    await update.message.reply_text(
        "🏠 ASOSIY MENYU\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu_keyboard(),
    )

    return MENU


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    user = update.effective_user

    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🚕 Surxon–Toshkent taksi xizmatiga xush kelibsiz.\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu_keyboard(),
    )

    return MENU


# ============================================================
# TAKSI BUYURTMASI
# ============================================================

async def start_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    keyboard = [
        [
            KeyboardButton(
                "📱 Telefon raqamimni yuborish",
                request_contact=True,
            )
        ],
        [
            KeyboardButton(
                "⬅️ Asosiy menyu"
            )
        ],
    ]

    markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await update.message.reply_text(
        "🚕 TAKSI BUYURTMASI\n\n"
        "Buyurtma berish uchun telefon raqamingizni "
        "yuboring.",
        reply_markup=markup,
    )

    return PHONE


# ============================================================
# TELEFON
# ============================================================

async def receive_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message
    user = update.effective_user

    if message.text == "⬅️ Asosiy menyu":

        return await show_main_menu(
            update,
            context,
        )

    if not message.contact:

        await message.reply_text(
            "❗ Iltimos, pastdagi tugma orqali "
            "o'zingizning telefon raqamingizni yuboring."
        )

        return PHONE

    contact = message.contact

    if (
        contact.user_id is not None
        and contact.user_id != user.id
    ):

        await message.reply_text(
            "❗ Iltimos, o'zingizning telefon "
            "raqamingizni yuboring."
        )

        return PHONE

    context.user_data["phone"] = contact.phone_number

    await message.reply_text(
        "✅ Telefon raqamingiz qabul qilindi.\n\n"
        "Endi safaringiz haqida ma'lumot yozing.\n\n"
        "Masalan:\n"
        "📍 Termizdan Toshkentga\n"
        "📅 5-sentabr\n"
        "⏰ Soat 07:00\n\n"
        "✏️ Qayerdan, qayerga va qachon "
        "borishingizni yozing.",
        reply_markup=back_menu_keyboard(),
    )

    return TRIP


# ============================================================
# SAFAR
# ============================================================

async def receive_trip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message
    user = update.effective_user

    if message.text == "⬅️ Asosiy menyu":

        return await show_main_menu(
            update,
            context,
        )

    trip = (message.text or "").strip()

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
            "Iltimos, /start orqali qaytadan boshlang.",
            reply_markup=main_menu_keyboard(),
        )

        context.user_data.clear()

        return MENU

    full_name = user.full_name or "Noma'lum"

    if user.username:

        username = f"@{user.username}"

    else:

        username = "Username yo'q"

    order_id = save_order(
        user.id,
        full_name,
        username,
        phone,
        trip,
    )

    # Mijozga javob
    await message.reply_text(
        "🙏 Buyurtmangiz uchun tashakkur!\n\n"
        "🚕 Haydovchilarimiz tez orada siz bilan "
        "bog'lanishadi.\n\n"
        "📞 Iltimos, telefoningizni kuzatib turing.",
        reply_markup=main_menu_keyboard(),
    )

    # Adminlarga yuboriladigan xabar
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
            "Adminlar ro'yxati bo'sh. "
            "Buyurtma #%s yuborilmadi.",
            order_id,
        )

    for admin_id in admins:

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
            )

        except Exception as error:

            logger.error(
                "Admin %s ga buyurtma #%s yuborilmadi: %s",
                admin_id,
                order_id,
                error,
            )

    context.user_data.clear()

    return MENU


# ============================================================
# QO'LLAB-QUVVATLASH
# ============================================================

async def start_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    await update.message.reply_text(
        "📞 QO'LLAB-QUVVATLASH\n\n"
        "Savol, taklif yoki muammoingiz bo'lsa, "
        "shu yerga yozing.\n\n"
        "👨‍💼 Operatorimiz xabaringizni ko'rib chiqadi "
        "va sizga javob beradi.\n\n"
        "✏️ Xabaringizni yozing:",
        reply_markup=back_menu_keyboard(),
    )

    return SUPPORT


async def receive_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message
    user = update.effective_user

    if message.text == "⬅️ Asosiy menyu":

        return await show_main_menu(
            update,
            context,
        )

    support_text = (message.text or "").strip()

    if not support_text:

        await message.reply_text(
            "❗ Iltimos, xabaringizni matn ko'rinishida yuboring."
        )

        return SUPPORT

    full_name = user.full_name or "Noma'lum"

    if user.username:

        username = f"@{user.username}"

    else:

        username = "Username yo'q"

    support_message = (
        "📞 QO'LLAB-QUVVATLASH XABARI\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Mijoz: {full_name}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "💬 MIJOZ XABARI:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{support_text}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "↩️ Mijozga javob berish uchun "
        "shu xabarga REPLY qiling."
    )

    admins = get_admins()

    if not admins:

        await message.reply_text(
            "⚠️ Hozircha operator mavjud emas.\n\n"
            "Iltimos, keyinroq qayta urinib ko'ring.",
            reply_markup=main_menu_keyboard(),
        )

        context.user_data.clear()

        return MENU

    sent_count = 0

    for admin_id in admins:

        try:

            sent_message = await context.bot.send_message(
                chat_id=admin_id,
                text=support_message,
            )

            save_support_message(
                client_id=user.id,
                admin_id=admin_id,
                admin_message_id=sent_message.message_id,
            )

            sent_count += 1

        except Exception as error:

            logger.error(
                "Support xabari admin %s ga yuborilmadi: %s",
                admin_id,
                error,
            )

    if sent_count > 0:

        await message.reply_text(
            "✅ Xabaringiz operatorga yuborildi.\n\n"
            "📞 Operatorimiz tez orada sizga javob beradi.",
            reply_markup=main_menu_keyboard(),
        )

    else:

        await message.reply_text(
            "⚠️ Xabaringizni operatorga yuborishda "
            "xatolik yuz berdi.\n\n"
            "Iltimos, keyinroq qayta urinib ko'ring.",
            reply_markup=main_menu_keyboard(),
        )

    context
