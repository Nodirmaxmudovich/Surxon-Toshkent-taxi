import os
import sqlite3
import logging
import threading
from datetime import datetime

from flask import Flask
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "taxi_bot.db"

MENU, PHONE, TRIP, SUPPORT = range(4)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN Render Environment Variables'da topilmadi.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("surxon_toshkent_taxi")

app = Flask(__name__)
db_lock = threading.Lock()


@app.get("/")
def home():
    return "Surxon-Toshkent Taxi Bot ishlayapti."


@app.get("/health")
def health():
    return "OK"


def run_web():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def db():
    c = sqlite3.connect(DB_FILE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db_lock:
        c = db()
        c.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            )
        """)
        c.execute("""
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                admin_id INTEGER NOT NULL,
                admin_message_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (admin_id, admin_message_id)
            )
        """)
        c.commit()
        c.close()

    for x in ADMIN_IDS.split(","):
        x = x.strip()
        if x.isdigit():
            add_admin(int(x))


def add_admin(user_id):
    with db_lock:
        c = db()
        c.execute(
            "INSERT OR IGNORE INTO admins(user_id, added_at) VALUES(?, ?)",
            (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        c.commit()
        c.close()


def remove_admin(user_id):
    with db_lock:
        c = db()
        c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        c.commit()
        c.close()


def is_admin(user_id):
    with db_lock:
        c = db()
        row = c.execute(
            "SELECT 1 FROM admins WHERE user_id=?", (user_id,)
        ).fetchone()
        c.close()
        return row is not None


def get_admins():
    with db_lock:
        c = db()
        rows = c.execute(
            "SELECT user_id FROM admins ORDER BY added_at"
        ).fetchall()
        c.close()
        return [r["user_id"] for r in rows]


def save_order(user_id, name, username, phone, trip):
    with db_lock:
        c = db()
        cur = c.execute("""
            INSERT INTO orders
            (user_id, full_name, username, phone, trip, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id, name, username, phone, trip,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        order_id = cur.lastrowid
        c.commit()
        c.close()
        return order_id


def save_support(admin_id, admin_message_id, client_id):
    with db_lock:
        c = db()
        c.execute("""
            INSERT OR REPLACE INTO support_messages
            (admin_id, admin_message_id, client_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            admin_id, admin_message_id, client_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        c.commit()
        c.close()


def find_support_client(admin_id, message_id):
    with db_lock:
        c = db()
        row = c.execute("""
            SELECT client_id FROM support_messages
            WHERE admin_id=? AND admin_message_id=?
        """, (admin_id, message_id)).fetchone()
        c.close()
        return row["client_id"] if row else None


def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚕 Taksi buyurtma qilish")],
        [KeyboardButton("📞 Qo'llab-quvvatlash")],
    ], resize_keyboard=True)


def back_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⬅️ Asosiy menyu")]], resize_keyboard=True
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "🚕 Surxon–Toshkent taksi xizmatiga xush kelibsiz.\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_keyboard(),
    )
    return MENU


async def menu_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚕 TAKSI BUYURTMASI\n\n"
        "Buyurtma berish uchun pastdagi tugma orqali "
        "telefon raqamingizni yuboring.",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📱 Telefon raqamimni yuborish", request_contact=True)],
            [KeyboardButton("⬅️ Asosiy menyu")],
        ], resize_keyboard=True),
    )
    return PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Asosiy menyu":
        return await start(update, context)

    contact = update.message.contact
    user = update.effective_user

    if not contact:
        await update.message.reply_text(
            "❗ Iltimos, pastdagi tugma orqali o'zingizning "
            "telefon raqamingizni yuboring."
        )
        return PHONE

    if contact.user_id is not None and contact.user_id != user.id:
        await update.message.reply_text(
            "❗ Iltimos, o'zingizning telefon raqamingizni yuboring."
        )
        return PHONE

    context.user_data["phone"] = contact.phone_number
    await update.message.reply_text(
        "✅ Telefon raqamingiz qabul qilindi.\n\n"
        "Endi qayerdan, qayerga va qachon borishingizni yozing.\n\n"
        "Masalan: Termizdan Toshkentga, 5-sentabr, soat 07:00.",
        reply_markup=back_keyboard(),
    )
    return TRIP


async def receive_trip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Asosiy menyu":
        return await start(update, context)

    trip = (update.message.text or "").strip()
    phone = context.user_data.get("phone")

    if not trip:
        await update.message.reply_text("❗ Safar ma'lumotini yozing.")
        return TRIP

    if not phone:
        await update.message.reply_text(
            "❗ Telefon raqamingiz topilmadi. /start orqali qaytadan boshlang.",
            reply_markup=main_keyboard(),
        )
        return MENU

    user = update.effective_user
    name = user.full_name or "Noma'lum"
    username = f"@{user.username}" if user.username else "Username yo'q"
    order_id = save_order(user.id, name, username, phone, trip)

    await update.message.reply_text(
        "🙏 Buyurtmangiz qabul qilindi!\n\n"
        "🚕 Haydovchilarimiz tez orada siz bilan bog'lanishadi.\n"
        "📞 Telefoningizni kuzatib turing.",
        reply_markup=main_keyboard(),
    )

    text = (
        "🚕 YANGI TAKSI BUYURTMASI\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Buyurtma: #{order_id}\n"
        f"👤 Mijoz: {name}\n"
        f"📱 Telefon: {phone}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "📍 SAFAR:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{trip}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )

    for admin_id in get_admins():
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Buyurtmani admin %s ga yuborishda xato", admin_id)

    context.user_data.clear()
    return MENU


async def menu_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 QO'LLAB-QUVVATLASH\n\n"
        "Savol, taklif yoki muammoingizni yozing.\n"
        "Operatorimiz sizga javob beradi.",
        reply_markup=back_keyboard(),
    )
    return SUPPORT


async def receive_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Asosiy menyu":
        return await start(update, context)

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❗ Xabaringizni yozing.")
        return SUPPORT

    user = update.effective_user
    name = user.full_name or "Noma'lum"
    username = f"@{user.username}" if user.username else "Username yo'q"
    admins = get_admins()

    if not admins:
        await update.message.reply_text(
            "⚠️ Hozircha operator mavjud emas. Keyinroq urinib ko'ring.",
            reply_markup=main_keyboard(),
        )
        return MENU

    admin_text = (
        "📞 QO'LLAB-QUVVATLASH XABARI\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Mijoz: {name}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "💬 XABAR:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{text}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "↩️ Javob berish uchun shu xabarga REPLY qiling."
    )

    sent = 0
    for admin_id in admins:
        try:
            msg = await context.bot.send_message(
                chat_id=admin_id, text=admin_text
            )
            save_support(admin_id, msg.message_id, user.id)
            sent += 1
        except Exception:
            logger.exception("Support xabarini admin %s ga yuborishda xato", admin_id)

    await update.message.reply_text(
        "✅ Xabaringiz operatorga yuborildi." if sent else
        "❌ Xabar operatorga yuborilmadi.",
        reply_markup=main_keyboard(),
    )
    return MENU


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user

    if not message or not user or not is_admin(user.id):
        return

    if not message.reply_to_message:
        return

    client_id = find_support_client(
        user.id, message.reply_to_message.message_id
    )
    if client_id is None:
        return

    text = (message.text or "").strip()
    if not text:
        await message.reply_text("❗ Faqat matnli javob yuboring.")
        return

    try:
        await context.bot.send_message(
            chat_id=client_id,
            text=f"👨‍💼 OPERATOR JAVOBI\n\n{text}",
        )
        await message.reply_text("✅ Javob mijozga yuborildi.")
    except Exception:
        logger.exception("Admin javobini mijozga yuborishda xato")
        await message.reply_text("❌ Javob yuborilmadi.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Jarayon bekor qilindi.\n\nAsosiy menyu:",
        reply_markup=main_keyboard(),
    )
    return MENU


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Sizning Telegram ID: {update.effective_user.id}"
    )


async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Faqat adminlar uchun.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Foydalanish: /addadmin TELEGRAM_ID"
        )
        return

    new_id = int(context.args[0])
    if is_admin(new_id):
        await update.message.reply_text("ℹ️ Bu foydalanuvchi allaqachon admin.")
        return

    add_admin(new_id)
    await update.message.reply_text(f"✅ Admin qo'shildi: {new_id}")


async def del_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔ Faqat adminlar uchun.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Foydalanish: /deladmin TELEGRAM_ID"
        )
        return

    remove_id = int(context.args[0])
    if remove_id == uid:
        await update.message.reply_text("❌ O'zingizni o'chira olmaysiz.")
        return

    if not is_admin(remove_id):
        await update.message.reply_text("ℹ️ Bu ID admin emas.")
        return

    remove_admin(remove_id)
    await update.message.reply_text(f"✅ Admin o'chirildi: {remove_id}")


async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Faqat adminlar uchun.")
        return

    admins = get_admins()
    if not admins:
        await update.message.reply_text("👮 Adminlar ro'yxati bo'sh.")
        return

    await update.message.reply_text(
        "👮 ADMINLAR:\n\n" +
        "\n".join(f"{i}. {x}" for i, x in enumerate(admins, 1))
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        text = (
            "🚕 ADMIN YORDAM\n\n"
            "/start — Asosiy menyu\n"
            "/myid — Telegram ID\n"
            "/admins — Adminlar\n"
            "/addadmin ID — Admin qo'shish\n"
            "/deladmin ID — Admin o'chirish\n"
            "/cancel — Bekor qilish\n\n"
            "📞 Support xabariga REPLY qilib mijozga javob bering."
        )
    else:
        text = (
            "🚕 TAKSI XIZMATI\n\n"
            "/start — Asosiy menyu\n"
            "/cancel — Bekor qilish"
        )
    await update.message.reply_text(text)


async def error_handler(update, context):
    logger.error("Bot xatosi", exc_info=context.error)


def main():
    init_db()

    threading.Thread(target=run_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, admin_reply),
        group=0,
    )

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [
                MessageHandler(
                    filters.Regex(r"^🚕 Taksi buyurtma qilish$"),
                    menu_order,
                ),
                MessageHandler(
                    filters.Regex(r"^📞 Qo'llab-quvvatlash$"),
                    menu_support,
                ),
            ],
            PHONE: [
                MessageHandler(filters.CONTACT, receive_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone),
            ],
            TRIP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_trip),
            ],
            SUPPORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(conversation, group=1)
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("myid", my_id))
    application.add_handler(CommandHandler("addadmin", add_admin_cmd))
    application.add_handler(CommandHandler("deladmin", del_admin_cmd))
    application.add_handler(CommandHandler("admins", admins_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_error_handler(error_handler)

    logger.info("Database ishga tushdi.")
    logger.info("Web server %s-portda ishga tushmoqda.", PORT)
    logger.info("SURXON-TOSHKENT TAXI BOT ISHGA TUSHDI!")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
