import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "bookings.db"))

(
    CHOOSE_ACTIVITY,
    ENTER_DATE,
    ENTER_TIME,
    ENTER_NAME,
    ENTER_PHONE,
    ENTER_COMMENT,
    CONFIRM,
) = range(7)

ACTIVITIES: Dict[str, str] = {
    "fishing": "🎣 Рыбалка",
    "hiking": "🥾 Поход",
    "ski": "⛷ Лыжи",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                activity_key TEXT NOT NULL,
                activity_name TEXT NOT NULL,
                booking_date TEXT NOT NULL,
                booking_time TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_booking(data: Dict[str, str], user_id: int, username: Optional[str]) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    with closing(get_connection()) as conn:
        cur = conn.execute(
            """
            INSERT INTO bookings (
                user_id,
                username,
                activity_key,
                activity_name,
                booking_date,
                booking_time,
                customer_name,
                customer_phone,
                comment,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                data["activity_key"],
                data["activity_name"],
                data["booking_date"],
                data["booking_time"],
                data["customer_name"],
                data["customer_phone"],
                data.get("comment", ""),
                created_at,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton(name, callback_data=key)]
        for key, name in ACTIVITIES.items()
    ]
    text = (
        "Добро пожаловать на туристическую базу!\n"
        "Выберите активность для бронирования:"
    )

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return CHOOSE_ACTIVITY


async def choose_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    activity_key = query.data
    if activity_key not in ACTIVITIES:
        await query.edit_message_text("Неизвестная активность. Нажмите /start и попробуйте снова.")
        return ConversationHandler.END

    context.user_data["activity_key"] = activity_key
    context.user_data["activity_name"] = ACTIVITIES[activity_key]

    await query.edit_message_text(
        f"Вы выбрали: {ACTIVITIES[activity_key]}\n"
        "Введите дату в формате ДД.ММ.ГГГГ (например, 15.07.2026)."
    )
    return ENTER_DATE


async def enter_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        parsed = datetime.strptime(text, "%d.%m.%Y")
        if parsed.date() < datetime.now().date():
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Неверная дата. Введите будущую дату в формате ДД.ММ.ГГГГ."
        )
        return ENTER_DATE

    context.user_data["booking_date"] = text
    await update.message.reply_text("Введите удобное время в формате ЧЧ:ММ (например, 09:30).")
    return ENTER_TIME


async def enter_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError:
        await update.message.reply_text("Неверное время. Используйте формат ЧЧ:ММ.")
        return ENTER_TIME

    context.user_data["booking_time"] = text
    await update.message.reply_text("Введите ваше имя и фамилию.")
    return ENTER_NAME


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Имя слишком короткое. Введите корректное имя.")
        return ENTER_NAME

    context.user_data["customer_name"] = name
    await update.message.reply_text("Введите номер телефона для связи.")
    return ENTER_PHONE


async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 10:
        await update.message.reply_text("Телефон выглядит некорректно. Повторите ввод.")
        return ENTER_PHONE

    context.user_data["customer_phone"] = phone
    await update.message.reply_text(
        "Добавьте комментарий к бронированию или отправьте '-' чтобы пропустить."
    )
    return ENTER_COMMENT


async def enter_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    comment = update.message.text.strip()
    context.user_data["comment"] = "" if comment == "-" else comment

    summary = (
        "Проверьте данные бронирования:\n"
        f"Активность: {context.user_data['activity_name']}\n"
        f"Дата: {context.user_data['booking_date']}\n"
        f"Время: {context.user_data['booking_time']}\n"
        f"Имя: {context.user_data['customer_name']}\n"
        f"Телефон: {context.user_data['customer_phone']}\n"
        f"Комментарий: {context.user_data['comment'] or '—'}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ]
    )

    await update.message.reply_text(summary, reply_markup=keyboard)
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Бронирование отменено. Чтобы начать заново, нажмите /start.")
        context.user_data.clear()
        return ConversationHandler.END

    user = query.from_user
    booking_id = save_booking(context.user_data, user.id, user.username)

    await query.edit_message_text(
        "✅ Бронирование подтверждено!\n"
        f"Номер брони: #{booking_id}. Мы свяжемся с вами для подтверждения."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT id, activity_name, booking_date, booking_time, created_at
            FROM bookings
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        await update.message.reply_text("У вас пока нет бронирований.")
        return

    lines = ["Ваши последние бронирования:"]
    for row in rows:
        lines.append(
            f"#{row['id']} {row['activity_name']} — {row['booking_date']} {row['booking_time']}"
        )

    await update.message.reply_text("\n".join(lines))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Диалог отменён. Для нового бронирования нажмите /start.")
    return ConversationHandler.END


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ACTIVITY: [CallbackQueryHandler(choose_activity)],
            ENTER_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date)],
            ENTER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_time)],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone)],
            ENTER_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_comment)],
            CONFIRM: [CallbackQueryHandler(confirm_booking, pattern="^(confirm|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("my_bookings", my_bookings))

    return app


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN environment variable")

    init_db()
    app = build_application(token)
    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
