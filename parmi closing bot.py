"""
PARMI — бот для чек-листа закрытия зала.

Как запустить:
1. pip install python-telegram-bot==21.*
2. Впишите свой токен от @BotFather в BOT_TOKEN ниже.
3. python parmi_closing_bot.py
4. Добавьте бота в рабочую группу в Телеграме.
5. В группе наберите /closing — появятся кнопки с зонами.

Состояние (что отмечено, что закрыто) хранится в памяти процесса
и сбрасывается каждый день автоматически (по дате). Если бот
перезапустится в течение дня — отметки за сегодня обнулятся,
это нормально для такого масштаба задачи.
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

BOT_TOKEN = os.environ["BOT_TOKEN"]

ZONES = {
    "hall": {
        "name": "Зал",
        "items": [
            "Протереть столы в зале",
            "Пополнить станции",
            "Поправить/протереть меню",
            "Протереть приборы и раздачу",
        ],
    },
    "veranda": {
        "name": "Веранда",
        "items": [
            "Закрыть веранду",
            "Убрать пепельницу",
            "Проверить мусорки, сменить пакет",
            "Сложить пледы",
            "Пополнить шкаф на веранде",
            "Протереть официантский стол на веранде",
        ],
    },
    "bar": {
        "name": "Расходники и бар",
        "items": [
            "Пополнить салфетки, трубочки, сахар",
            "Пополнить холодильник и шкаф с тёплыми напитками",
            "Сдать тряпки на мойку",
            "Помыть и заполнить водой миску",
        ],
    },
}

# state[chat_id][zone_id] = {"checked": {idx, ...}, "date": "YYYY-MM-DD", "closed": bool}
state = {}


def today():
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


def get_zone_state(chat_id, zone_id):
    chat_state = state.setdefault(chat_id, {})
    zs = chat_state.get(zone_id)
    if zs is None or zs["date"] != today():
        zs = {"checked": set(), "date": today(), "closed": False}
        chat_state[zone_id] = zs
    return zs


def zones_keyboard(chat_id):
    rows = []
    for zid, z in ZONES.items():
        zs = get_zone_state(chat_id, zid)
        mark = "✅" if zs["closed"] else "🧹"
        rows.append([InlineKeyboardButton(f"{mark} {z['name']}", callback_data=f"open:{zid}")])
    return InlineKeyboardMarkup(rows)


def checklist_keyboard(chat_id, zone_id):
    zone = ZONES[zone_id]
    zs = get_zone_state(chat_id, zone_id)
    rows = []
    for idx, item in enumerate(zone["items"]):
        mark = "✅" if idx in zs["checked"] else "⬜️"
        rows.append([InlineKeyboardButton(f"{mark} {item}", callback_data=f"toggle:{zone_id}:{idx}")])
    all_done = len(zs["checked"]) == len(zone["items"])
    if all_done and not zs["closed"]:
        rows.append([InlineKeyboardButton("✅ Завершить зону", callback_data=f"finish:{zone_id}")])
    rows.append([InlineKeyboardButton("« Назад к зонам", callback_data="back")])
    return InlineKeyboardMarkup(rows)


async def cmd_closing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "Чек-лист закрытия — выберите зону:",
        reply_markup=zones_keyboard(chat_id),
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "back":
        await query.edit_message_text(
            "Чек-лист закрытия — выберите зону:",
            reply_markup=zones_keyboard(chat_id),
        )
        return

    if data.startswith("open:"):
        zone_id = data.split(":")[1]
        zone = ZONES[zone_id]
        zs = get_zone_state(chat_id, zone_id)
        status = "уже закрыта сегодня ✅" if zs["closed"] else "открыта"
        await query.edit_message_text(
            f"{zone['name']} ({status})\nОтмечайте пункты:",
            reply_markup=checklist_keyboard(chat_id, zone_id),
        )
        return

    if data.startswith("toggle:"):
        _, zone_id, idx = data.split(":")
        idx = int(idx)
        zs = get_zone_state(chat_id, zone_id)
        if zs["closed"]:
            await query.answer("Зона уже закрыта сегодня", show_alert=True)
            return
        if idx in zs["checked"]:
            zs["checked"].remove(idx)
        else:
            zs["checked"].add(idx)
        zone = ZONES[zone_id]
        await query.edit_message_text(
            f"{zone['name']}\nОтмечайте пункты:",
            reply_markup=checklist_keyboard(chat_id, zone_id),
        )
        return

    if data.startswith("finish:"):
        zone_id = data.split(":")[1]
        zone = ZONES[zone_id]
        zs = get_zone_state(chat_id, zone_id)
        zs["closed"] = True
        user = query.from_user.full_name
        now = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
        report = (
            f"✅ ЗАКРЫТИЕ — {zone['name'].upper()}\n"
            f"{now}\n"
            f"Закрыл(а): {user}\n\n"
            + "\n".join(f"✓ {item}" for item in zone["items"])
        )
        # Публикуем итог отдельным сообщением в чат — это и есть журнал.
        await context.bot.send_message(chat_id=chat_id, text=report)
        await query.edit_message_text(
            "Чек-лист закрытия — выберите зону:",
            reply_markup=zones_keyboard(chat_id),
        )
        return


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("closing", cmd_closing))
    app.add_handler(CallbackQueryHandler(on_button))
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
