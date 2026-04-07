import os
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from shared_config import load_config, save_config

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

user_states: dict[int, str] = {}


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    text = (
        "Команды:\n"
        "/status\n"
        "/enable\n"
        "/disable\n"
        "/set_target\n"
        "/set_sources\n"
        "/add_source\n"
        "/clear_sources\n"
        "/set_replace\n"
        "/clear_replace\n"
    )
    await update.message.reply_text(text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    config = load_config()
    text = (
        f"enabled: {config.get('enabled')}\n"
        f"target: {config.get('target_channel')}\n"
        f"sources: {config.get('source_channels')}\n"
        f"replace_list: {config.get('replace_list')}"
    )
    await update.message.reply_text(text)


async def enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    config = load_config()
    config["enabled"] = True
    save_config(config)
    await update.message.reply_text("Включено")


async def disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    config = load_config()
    config["enabled"] = False
    save_config(config)
    await update.message.reply_text("Выключено")


async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    user_states[update.effective_user.id] = "set_target"
    await update.message.reply_text("Отправь username target-канала без @ и без https://")


async def set_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    user_states[update.effective_user.id] = "set_sources"
    await update.message.reply_text("Отправь source-каналы через запятую, без @ и без https://")


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    user_states[update.effective_user.id] = "add_source"
    await update.message.reply_text("Отправь один source-канал")


async def clear_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    config = load_config()
    config["source_channels"] = []
    save_config(config)
    await update.message.reply_text("Список source очищен")


async def set_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    user_states[update.effective_user.id] = "set_replace"
    await update.message.reply_text("Отправь замены в формате:\nстарое=>новое\nстрока2=>строка2")


async def clear_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    config = load_config()
    config["replace_list"] = []
    save_config(config)
    await update.message.reply_text("replace_list очищен")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state:
        return

    text = update.message.text.strip()
    config = load_config()

    if state == "set_target":
        config["target_channel"] = text.lstrip("@").strip()
        save_config(config)
        await update.message.reply_text(f"target сохранен: {config['target_channel']}")

    elif state == "set_sources":
        items = [x.strip().lstrip("@") for x in text.split(",") if x.strip()]
        config["source_channels"] = items
        save_config(config)
        await update.message.reply_text(f"source_channels сохранены: {items}")

    elif state == "add_source":
        item = text.lstrip("@").strip()
        sources = config.get("source_channels", [])
        if item and item not in sources:
            sources.append(item)
        config["source_channels"] = sources
        save_config(config)
        await update.message.reply_text(f"добавлен source: {item}")

    elif state == "set_replace":
        rules = []
        for line in text.splitlines():
            line = line.strip()
            if not line or "=>" not in line:
                continue
            old, new = line.split("=>", 1)
            rules.append([old, new])

        config["replace_list"] = rules
        save_config(config)
        await update.message.reply_text(f"replace_list сохранен: {rules}")

    user_states.pop(user_id, None)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("enable", enable))
    app.add_handler(CommandHandler("disable", disable))
    app.add_handler(CommandHandler("set_target", set_target))
    app.add_handler(CommandHandler("set_sources", set_sources))
    app.add_handler(CommandHandler("add_source", add_source))
    app.add_handler(CommandHandler("clear_sources", clear_sources))
    app.add_handler(CommandHandler("set_replace", set_replace))
    app.add_handler(CommandHandler("clear_replace", clear_replace))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main()