import os
import sqlite3
import logging
import threading
import asyncio
from datetime import datetime
from html import escape

from flask import Flask, request, jsonify
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

DRIVERS_GROUP_ID = int(os.getenv("DRIVERS_GROUP_ID", "-1004297712188"))
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")

DB_FILE = "taxi_bot.db"

PHONE, TRIP, SUPPORT = range(3)

# Flask webhook threadidan Telegram coroutine'larini
# asosiy asyncio event loop'iga yuborish uchun.
BOT_LOOP = None
bot_application = None

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("surxon_toshkent_taxi")

# =========================================================
# FLASK
# =========================================================

web_app = Flask(__name__)


@web_app.route("/", methods=["GET"])
def home():
    return "Surxon-Toshkent Taxi Bot ishlayapti."


@web_app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "surxon-toshkent-taxi",
    })


WEBHOOK_PATH = f"/telegram/{BOT_TOKEN}"


@web_app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    """
    Telegram webhookidan kelgan update'ni asosiy
    asyncio event loop'ida xavfsiz qayta ishlaydi.
    """
    global BOT_LOOP

    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({"ok": False, "error": "empty update"}), 400

        if bot_application is None or BOT_LOOP is None:
            logger.error("Bot hali event loopga ulanmagan.")
            return jsonify({"ok": False, "error": "bot not ready"}), 503

        update = Update.de_json(data, bot_application.bot)

        # Flask alohida threadda ishlaydi.
        # Coroutine'ni aynan botning asosiy event loop'iga yuboramiz.
        future = asyncio.run_coroutine_threadsafe(
            bot_application.process_update(update),
            BOT_LOOP,
        )

        # Telegram webhookga tezda 200 qaytaramiz.
        # Update esa asosiy asyncio loop'ida qayta ishlanadi.
        logger.info("Telegram update qabul qilindi.")
        return jsonify({"ok": True})

    except Exception as error:
        logger.exception("Webhook xatosi: %s", error)
        return jsonify({"ok": False}), 500


def run_web_server():
    web_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# DATABASE
# =========================================================

db_lock = threading.Lock()


def get_connection():
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with db_lock:
        connection = get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    full_name TEXT,
                    username TEXT,
                    phone TEXT NOT NULL,
                    trip TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            connection.commit()

        finally:
            connection.close()

    if ADMIN_IDS_ENV:
        for value in ADMIN_IDS_ENV.split(","):
            value = value.strip()

            if not value:
                continue

            try:
                add_admin(int(value))
            except ValueError:
                logger.warning(
                    "ADMIN_IDS ichida noto'g'ri ID: %s",
                    value,
                )


def add_admin(user_id: int):
    with db_lock:
        connection = get_connection()

        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO admins
                (user_id, added_at)
                VALUES (?, ?)
                """,
                (
                    user_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            connection.commit()

        finally:
            connection.close()


def remove_admin(user_id: int):
    with db_lock:
        connection = get_connection()

        try:
            connection.execute(
                "DELETE FROM admins WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()

        finally:
            connection.close()


def is_admin(user_id: int) -> bool:
    with db_lock:
        connection = get_connection()

        try:
            result = connection.execute(
                """
                SELECT user_id
                FROM admins
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            return result is not None

        finally:
            connection.close()


def get_admins():
    with db_lock:
        connection = get_connection()

        try:
            return connection.execute(
                """
                SELECT user_id, added_at
                FROM admins
                ORDER BY added_at ASC
                """
            ).fetchall()

        finally:
            connection.close()


def save_order(
    user_id: int,
    full_name: str,
    username: str,
    phone: str,
    trip: str,
):
    with db_lock:
        connection = get_connection()

        try:
            cursor = connection.execute(
                """
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
                """,
                (
                    user_id,
                    full_name,
                    username,
                    phone,
                    trip,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

            connection.commit()
            return cursor.lastrowid

        finally:
            connection.close()


# =========================================================
# KLAVIATURALAR
# =========================================================

def main_menu():
    keyboard = [
        [KeyboardButton("🚕 Taksi buyurtma qilish")],
        [KeyboardButton("📞 Qo'llab-quvvatlash")],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
    )


def phone_menu():
    keyboard = [
        [
            KeyboardButton(
                "📱 Telefon raqamimni yuborish",
                request_contact=True,
            )
        ],
        [KeyboardButton("📞 Qo'llab-quvvatlash")],
        [KeyboardButton("❌ Bekor qilish")],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
    )


def cancel_menu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Bekor qilish")]],
        resize_keyboard=True,
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "🚕 <b>Surxondaryo — Toshkent taksi xizmatiga</b> "
        "xush kelibsiz.\n\n"
        "Kerakli xizmatni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

    return ConversationHandler.END


# =========================================================
# BUYURTMA BOSHLASH
# =========================================================

async def start_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(
        "🚕 <b>Taksi buyurtmasi</b>\n\n"
        "Avvalo telefon raqamingizni yuboring.\n\n"
        "📱 Quyidagi tugmani bosing:",
        parse_mode=ParseMode.HTML,
        reply_markup=phone_menu(),
    )

    return PHONE


# =========================================================
# TELEFON
# =========================================================

async def receive_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message
    user = update.effective_user

    if not message or not user:
        return PHONE

    if message.text == "📞 Qo'llab-quvvatlash":
        await message.reply_text(
            "📞 <b>Qo'llab-quvvatlash</b>\n\n"
            "Savolingiz yoki muammoingizni yozib yuboring.\n"
            "Xabaringiz operatorga yuboriladi.",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_menu(),
        )
        return SUPPORT

    if message.text == "❌ Bekor qilish":
        context.user_data.clear()

        await message.reply_text(
            "❌ Buyurtma bekor qilindi.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if not message.contact:
        await message.reply_text(
            "⚠️ Iltimos, telefon raqamingizni qo'lda yozmang.\n\n"
            "📱 <b>Telefon raqamimni yuborish</b> "
            "tugmasini bosing.",
            parse_mode=ParseMode.HTML,
            reply_markup=phone_menu(),
        )
        return PHONE

    contact = message.contact

    if (
        contact.user_id is not None
        and contact.user_id != user.id
    ):
        await message.reply_text(
            "⚠️ Faqat o'zingizning telefon raqamingizni "
            "yuborishingiz mumkin.",
            reply_markup=phone_menu(),
        )
        return PHONE

    context.user_data["phone"] = contact.phone_number

    await message.reply_text(
        "✅ Telefon raqamingiz qabul qilindi.\n\n"
        "Endi safar ma'lumotlarini yozing.\n\n"
        "Masalan:\n"
        "<i>Termizdan Toshkentga.\n"
        "5-sentabr kuni soat 08:00 da.</i>\n\n"
        "Yoki o'zingizga qulay tarzda batafsil yozishingiz mumkin.",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_menu(),
    )

    return TRIP


# =========================================================
# SAFAR
# =========================================================

async def receive_trip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        return TRIP

    text = message.text.strip()

    if text == "❌ Bekor qilish":
        context.user_data.clear()

        await message.reply_text(
            "❌ Buyurtma bekor qilindi.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    phone = context.user_data.get("phone")

    if not phone:
        await message.reply_text(
            "⚠️ Telefon raqamingiz topilmadi.\n"
            "Iltimos, buyurtmani qaytadan boshlang.",
            reply_markup=main_menu(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    if len(text) < 3:
        await message.reply_text(
            "⚠️ Safar ma'lumotlarini biroz batafsilroq yozing.\n\n"
            "Masalan:\n"
            "Termizdan Toshkentga, ertalab soat 08:00."
        )
        return TRIP

    full_name = user.full_name or "Noma'lum"
    username = f"@{user.username}" if user.username else "Username yo'q"

    order_id = save_order(
        user_id=user.id,
        full_name=full_name,
        username=username,
        phone=phone,
        trip=text,
    )

    order_time = datetime.now().strftime("%d.%m.%Y %H:%M")

    safe_name = escape(full_name)
    safe_username = escape(username)
    safe_phone = escape(phone)
    safe_trip = escape(text)

    drivers_message = (
        "🚕 <b>YANGI TAKSI BUYURTMASI!</b>\n\n"
        f"🆔 <b>Buyurtma:</b> #{order_id}\n"
        f"👤 <b>Mijoz:</b> {safe_name}\n"
        f"📞 <b>Telefon:</b> {safe_phone}\n"
        f"💬 <b>Telegram:</b> {safe_username}\n"
        f"📝 <b>Safar:</b> {safe_trip}\n"
        f"🕐 <b>Buyurtma vaqti:</b> {order_time}\n\n"
        "🚗 <b>Kim oladi?</b>"
    )

    drivers_sent = False

    try:
        await context.bot.send_message(
            chat_id=DRIVERS_GROUP_ID,
            text=drivers_message,
            parse_mode=ParseMode.HTML,
        )
        drivers_sent = True

    except Exception as error:
        logger.exception(
            "Haydovchilar guruhiga yuborishda xato: %s",
            error,
        )

    if drivers_sent:
        client_text = (
            "✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
            f"🆔 Buyurtma raqami: <b>#{order_id}</b>\n"
            f"📞 Telefon: {safe_phone}\n"
            f"📝 Safar: {safe_trip}\n\n"
            "🚕 Buyurtmangiz haydovchilarga yuborildi.\n"
            "Tez orada haydovchi bilan bog'lanishadi."
        )
    else:
        client_text = (
            "⚠️ <b>Buyurtmangiz saqlandi.</b>\n\n"
            f"🆔 Buyurtma raqami: <b>#{order_id}</b>\n"
            f"📝 Safar: {safe_trip}\n\n"
            "Operator buyurtmangizni tekshirib, "
            "siz bilan bog'lanadi."
        )

    await message.reply_text(
        client_text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

    admins = get_admins()

    admin_message = (
        "📢 <b>YANGI BUYURTMA</b>\n\n"
        f"🆔 <b>Buyurtma:</b> #{order_id}\n"
        f"👤 <b>Mijoz:</b> {safe_name}\n"
        f"📞 <b>Telefon:</b> {safe_phone}\n"
        f"💬 <b>Telegram:</b> {safe_username}\n"
        f"🔢 <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"📝 <b>Safar:</b> {safe_trip}\n"
        f"🕐 <b>Vaqt:</b> {order_time}\n"
    )

    for admin in admins:
        try:
            await context.bot.send_message(
                chat_id=admin["user_id"],
                text=admin_message,
                parse_mode=ParseMode.HTML,
            )
        except Exception as error:
            logger.warning(
                "Admin %s ga yuborilmadi: %s",
                admin["user_id"],
                error,
            )

    context.user_data.clear()
    return ConversationHandler.END


# =========================================================
# QO'LLAB-QUVVATLASH
# =========================================================

async def start_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(
        "📞 <b>Qo'llab-quvvatlash</b>\n\n"
        "Savolingiz yoki muammoingizni yozing.\n"
        "Xabaringiz operatorlarga yuboriladi.",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_menu(),
    )

    return SUPPORT


async def receive_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        return SUPPORT

    text = message.text.strip()

    if text == "❌ Bekor qilish":
        context.user_data.clear()

        await message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if len(text) < 2:
        await message.reply_text(
            "⚠️ Iltimos, xabaringizni yozing."
        )
        return SUPPORT

    full_name = user.full_name or "Noma'lum"
    username = f"@{user.username}" if user.username else "Username yo'q"

    support_message = (
        "📞 <b>QO'LLAB-QUVVATLASH XABARI</b>\n\n"
        f"👤 <b>Mijoz:</b> {escape(full_name)}\n"
        f"💬 <b>Telegram:</b> {escape(username)}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.id}</code>\n\n"
        f"💬 <b>Xabar:</b>\n{escape(text)}\n\n"
        "Javob berish:\n"
        f"<code>/reply {user.id} Javobingiz</code>"
    )

    admins = get_admins()
    sent_count = 0

    for admin in admins:
        try:
            await context.bot.send_message(
                chat_id=admin["user_id"],
                text=support_message,
                parse_mode=ParseMode.HTML,
            )
            sent_count += 1
        except Exception as error:
            logger.warning(
                "Support admin xatosi: %s",
                error,
            )

    if sent_count > 0:
        await message.reply_text(
            "✅ Xabaringiz operatorga yuborildi.\n\n"
            "Tez orada siz bilan bog'lanishadi.",
            reply_markup=main_menu(),
        )
    else:
        await message.reply_text(
            "⚠️ Hozircha operator mavjud emas.\n"
            "Iltimos, birozdan keyin qayta urinib ko'ring.",
            reply_markup=main_menu(),
        )

    context.user_data.clear()
    return ConversationHandler.END


# =========================================================
# BEKOR QILISH
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    if update.message:
        await update.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=main_menu(),
        )

    return ConversationHandler.END


# =========================================================
# MY ID
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    await update.message.reply_text(
        "🆔 Sizning Telegram ID raqamingiz:\n\n"
        f"<code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# ADMIN
# =========================================================

async def add_admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("⛔ Sizda admin huquqi yo'q.")
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "<code>/addadmin 123456789</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Telegram ID faqat raqam bo'lishi kerak."
        )
        return

    add_admin(new_admin_id)

    await update.message.reply_text(
        f"✅ <code>{new_admin_id}</code> admin qilib qo'shildi.",
        parse_mode=ParseMode.HTML,
    )


async def delete_admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("⛔ Sizda admin huquqi yo'q.")
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "<code>/deladmin 123456789</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Telegram ID faqat raqam bo'lishi kerak."
        )
        return

    if admin_id == user_id:
        await update.message.reply_text(
            "⚠️ O'zingizni adminlar ro'yxatidan o'chira olmaysiz."
        )
        return

    remove_admin(admin_id)

    await update.message.reply_text(
        f"✅ <code>{admin_id}</code> adminlar ro'yxatidan o'chirildi.",
        parse_mode=ParseMode.HTML,
    )


async def admins_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("⛔ Sizda admin huquqi yo'q.")
        return

    admins = get_admins()

    if not admins:
        await update.message.reply_text("Adminlar ro'yxati bo'sh.")
        return

    text = "👨‍💼 <b>ADMINLAR</b>\n\n"

    for index, admin in enumerate(admins, start=1):
        text += f"{index}. <code>{admin['user_id']}</code>\n"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# ADMIN REPLY
# =========================================================

async def reply_to_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        await update.message.reply_text("⛔ Sizda admin huquqi yo'q.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Foydalanish:\n\n"
            "<code>/reply USER_ID Javobingiz</code>\n\n"
            "Masalan:\n"
            "<code>/reply 123456789 "
            "Assalomu alaykum, qanday yordam beray?</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ USER_ID noto'g'ri.")
        return

    reply_text = " ".join(context.args[1:]).strip()

    if not reply_text:
        await update.message.reply_text(
            "⚠️ Javob matni bo'sh bo'lmasin."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                "📞 <b>Operator javobi:</b>\n\n"
                f"{escape(reply_text)}"
            ),
            parse_mode=ParseMode.HTML,
        )

        await update.message.reply_text(
            "✅ Javob mijozga yuborildi."
        )

    except Exception as error:
        logger.exception(
            "Mijozga javob yuborishda xato: %s",
            error,
        )

        await update.message.reply_text(
            "❌ Mijozga xabar yuborilmadi.\n"
            "U botni bloklagan yoki Telegram ID noto'g'ri bo'lishi mumkin."
        )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    if is_admin(user_id):
        text = (
            "👨‍💼 <b>ADMIN YORDAMI</b>\n\n"
            "/start — Botni boshlash\n"
            "/myid — Telegram ID\n"
            "/admins — Adminlar ro'yxati\n"
            "/addadmin ID — Admin qo'shish\n"
            "/deladmin ID — Admin o'chirish\n"
            "/reply ID matn — Mijozga javob berish\n"
            "/cancel — Amalni bekor qilish"
        )
    else:
        text = (
            "ℹ️ <b>YORDAM</b>\n\n"
            "🚕 Taksi buyurtma qilish — yangi buyurtma\n"
            "📞 Qo'llab-quvvatlash — operator bilan bog'lanish\n"
            "/myid — Telegram ID\n"
            "/cancel — Amalni bekor qilish"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.exception(
        "Telegram update xatosi:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    global bot_application, BOT_LOOP

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN Render Environment Variables ichida topilmadi."
        )

    init_database()

    bot_application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # CONVERSATION
    # =====================================================

    conversation_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^🚕 Taksi buyurtma qilish$"),
                start_order,
            ),
            MessageHandler(
                filters.Regex(r"^📞 Qo'llab-quvvatlash$"),
                start_support,
            ),
        ],

        states={
            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    receive_phone,
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_phone,
                ),
            ],

            TRIP: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_trip,
                ),
            ],

            SUPPORT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_support,
                ),
            ],
        },

        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],

        allow_reentry=True,
    )

    bot_application.add_handler(conversation_handler)

    # /start alohida ishlaydi va asosiy menyuni chiqaradi.
    bot_application.add_handler(
        CommandHandler("start", start)
    )

    bot_application.add_handler(
        CommandHandler("cancel", cancel)
    )

    bot_application.add_handler(
        CommandHandler("myid", my_id)
    )

    bot_application.add_handler(
        CommandHandler("addadmin", add_admin_command)
    )

    bot_application.add_handler(
        CommandHandler("deladmin", delete_admin_command)
    )

    bot_application.add_handler(
        CommandHandler("admins", admins_command)
    )

    bot_application.add_handler(
        CommandHandler("reply", reply_to_user)
    )

    bot_application.add_handler(
        CommandHandler("help", help_command)
    )

    bot_application.add_error_handler(error_handler)

    # =====================================================
    # FLASK SERVER
    # =====================================================

    server_thread = threading.Thread(
        target=run_web_server,
        daemon=True,
        name="flask-server",
    )

    server_thread.start()

    # =====================================================
    # TELEGRAM BOT
    # =====================================================

    async def start_bot():
        global BOT_LOOP

        # Eng muhim qism:
        # webhook threadi aynan shu event loop'dan foydalanadi.
        BOT_LOOP = asyncio.get_running_loop()

        await bot_application.initialize()
        await bot_application.start()

        if RENDER_EXTERNAL_URL:
            webhook_url = (
                f"{RENDER_EXTERNAL_URL}"
                f"/telegram/{BOT_TOKEN}"
            )

            await bot_application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )

            # Tokenni logga to'liq chiqarmaymiz.
            logger.info(
                "Telegram webhook o'rnatildi: %s/telegram/[TOKEN]",
                RENDER_EXTERNAL_URL,
            )
        else:
            logger.warning(
                "RENDER_EXTERNAL_URL topilmadi."
            )

        logger.info("Telegram bot ishga tayyor.")

        try:
            await asyncio.Event().wait()
        finally:
            await bot_application.stop()
            await bot_application.shutdown()
            BOT_LOOP = None

    try:
        asyncio.run(start_bot())

    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi.")

    except Exception as error:
        logger.exception(
            "Bot ishga tushishida xato: %s",
            error,
        )


if __name__ == "__main__":
    main()
