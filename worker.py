import asyncio
import logging
import os
from typing import Any

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from loguru import logger

from shared_config import SESSION_NAME, load_config, load_state, save_state

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["PHONE"]

PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
PROXY_TYPE = os.getenv("PROXY_TYPE", "socks5").strip()
PROXY_HOST = os.getenv("PROXY_HOST", "").strip()
PROXY_PORT = int(os.getenv("PROXY_PORT", "1080"))
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "").strip()
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "").strip()

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "30"))
SEND_DELAY = float(os.getenv("SEND_DELAY", "1"))
USE_IPV6 = os.getenv("USE_IPV6", "false").lower() == "true"

logging.basicConfig(level=logging.INFO)
logger.add("worker.log", rotation="1 MB", encoding="utf-8", enqueue=True)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


def build_proxy():
    if not PROXY_ENABLED:
        return None

    if not PROXY_HOST:
        raise RuntimeError("PROXY_ENABLED=true, но PROXY_HOST пустой")

    if PROXY_USERNAME or PROXY_PASSWORD:
        return (PROXY_TYPE, PROXY_HOST, PROXY_PORT, True, PROXY_USERNAME, PROXY_PASSWORD)

    return (PROXY_TYPE, PROXY_HOST, PROXY_PORT)


client = TelegramClient(
    SESSION_NAME,
    API_ID,
    API_HASH,
    proxy=build_proxy(),
    use_ipv6=USE_IPV6,
    connection_retries=20,
    retry_delay=3,
    timeout=20,
    request_retries=5,
    auto_reconnect=True,
)

resolved_target: Any = None
resolved_sources: dict[str, Any] = {}


def replace_text(text: str, replace_list) -> str:
    text = text or ""
    for old, new in replace_list:
        text = text.replace(old, new)
    return text


async def auth():
    await client.connect()
    print("Подключились к Telegram")

    if await client.is_user_authorized():
        print("Уже авторизован")
        return

    await client.send_code_request(PHONE)
    code = input("Введи код из Telegram: ").strip()

    try:
        await client.sign_in(phone=PHONE, code=code)
    except SessionPasswordNeededError:
        password = input("Введи пароль 2FA: ").strip()
        await client.sign_in(password=password)

    print("Авторизация успешна")


async def resolve_entities():
    global resolved_target, resolved_sources

    config = load_config()
    target_channel = config.get("target_channel", "").strip()
    source_channels = config.get("source_channels", [])

    if not target_channel or not source_channels:
        resolved_target = None
        resolved_sources = {}
        return

    resolved_target = await client.get_entity(target_channel)
    resolved_sources = {}

    for src in source_channels:
        entity = await client.get_entity(src)
        resolved_sources[src] = entity


async def init_missing_state():
    state = load_state()

    for src_name, src_entity in resolved_sources.items():
        if src_name in state:
            continue

        msgs = await client.get_messages(src_entity, limit=1)
        state[src_name] = msgs[0].id if msgs else 0

    save_state(state)


async def send_single_message(msg, replace_list):
    text = replace_text(msg.message or "", replace_list)

    if msg.media:
        await client.send_file(resolved_target, msg.media, caption=text or "")
        print(f"[SEND] single media | id={msg.id}")
    elif text.strip():
        await client.send_message(resolved_target, text)
        print(f"[SEND] single text | id={msg.id}")
    else:
        print(f"[SKIP] empty | id={msg.id}")


async def send_album(messages, replace_list):
    files = []
    caption = ""

    for msg in messages:
        if msg.media:
            files.append(msg.media)
        if not caption and (msg.message or "").strip():
            caption = replace_text(msg.message or "", replace_list)

    if not files:
        for msg in messages:
            await send_single_message(msg, replace_list)
        return

    await client.send_file(resolved_target, files, caption=caption or "")
    print(f"[SEND] album | ids={[m.id for m in messages]}")


def split_by_album(messages):
    result = []
    i = 0

    while i < len(messages):
        msg = messages[i]
        grouped_id = getattr(msg, "grouped_id", None)

        if not grouped_id:
            result.append([msg])
            i += 1
            continue

        group = [msg]
        i += 1

        while i < len(messages) and getattr(messages[i], "grouped_id", None) == grouped_id:
            group.append(messages[i])
            i += 1

        result.append(group)

    return result


async def process_source(src_name: str, src_entity, state: dict, replace_list):
    last_id = state.get(src_name, 0)
    msgs = await client.get_messages(src_entity, limit=FETCH_LIMIT)

    if not msgs:
        return

    msgs = list(reversed(msgs))
    new_msgs = [m for m in msgs if m.id > last_id]

    if not new_msgs:
        return

    groups = split_by_album(new_msgs)

    for group in groups:
        if len(group) == 1:
            await send_single_message(group[0], replace_list)
            state[src_name] = group[0].id
        else:
            await send_album(group, replace_list)
            state[src_name] = max(m.id for m in group)

        save_state(state)
        await asyncio.sleep(SEND_DELAY)


async def main():
    await auth()
    last_config_snapshot = None

    while True:
        try:
            config = load_config()

            if not config.get("enabled", False):
                print("Worker paused")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            current_snapshot = (
                config.get("target_channel", ""),
                tuple(config.get("source_channels", [])),
                tuple(tuple(x) for x in config.get("replace_list", [])),
            )

            if current_snapshot != last_config_snapshot:
                await resolve_entities()
                await init_missing_state()
                last_config_snapshot = current_snapshot
                print("Config reloaded")

            if not resolved_target or not resolved_sources:
                print("Нет target/source")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            state = load_state()
            replace_list = config.get("replace_list", [])

            for src_name, src_entity in resolved_sources.items():
                await process_source(src_name, src_entity, state, replace_list)

        except Exception as e:
            logger.exception(f"Worker error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    finally:
        loop.run_until_complete(client.disconnect())
        loop.close()