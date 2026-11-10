"""Manba kanallardagi YANGI xabarlarni manzil kanaliga nusxalash (forward emas, manba nomi ko'rinmaydi).

Signal boti bilan BITTA Telegram ulanishida ishlaydi (alohida sessiya fayli shart emas, "database is locked" bo'lmaydi).
Xatti-harakat: eski xabarlar ko'chirilmaydi; javoblar nusxalangan ota xabarga ulanadi; himoyalangan postlar va
nusxalanmagan ota xabarga javoblar tashlab ketiladi. Logga xabar matni, havola yoki maxfiy ma'lumot yozilmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger("apexbot.forwarder")
MAX_FLOOD_WAIT = 120  # bundan uzun kutish so'ralsa xabar tashlab ketiladi


class MessageMapStore:
    """Manba xabar ID -> manzil xabar ID (javoblarni bog'lash uchun)."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS message_map (
                   source_chat_id INTEGER NOT NULL, source_message_id INTEGER NOT NULL,
                   destination_message_id INTEGER NOT NULL,
                   PRIMARY KEY (source_chat_id, source_message_id))""")
        self.connection.commit()

    def get(self, chat_id: int, message_id: int):
        row = self.connection.execute(
            "SELECT destination_message_id FROM message_map WHERE source_chat_id = ? AND source_message_id = ?",
            (chat_id, message_id)).fetchone()
        return row[0] if row else None

    def put(self, chat_id: int, message_id: int, destination_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO message_map VALUES (?, ?, ?)", (chat_id, message_id, destination_id))

    def close(self) -> None:
        self.connection.close()


AD_WORDS = re.compile(
    r"раздач|розыгрыш|конкурс|бонус|промокод|реферал|партн[её]р|регистрир|регистрац|депозит|giveaway|airdrop|"
    r"bingx|bybit|okx|mexc|bitget|kucoin|gate\.io|подпис(ывай|аться|ка)|переходи|жми|kazino|казино|ставк[аи] на", re.I)
URL_RE = re.compile(r"(?:https?://|www\.|t\.me/)\S+", re.I)
CTA_LINE = re.compile(r"открыть сделку|открыть позицию|торговать здесь|ссылка|регистрац", re.I)


def clean_signal_text(text: str) -> str:
    """Signal matnidan begona havola/CTA satrlarini olib tashlaydi ("➡️ Открыть сделку" va h.k.)."""
    lines = [ln for ln in text.splitlines() if not CTA_LINE.search(ln) and not URL_RE.search(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def ad_reason(text: str, has_link_entities: bool = False, has_buttons: bool = False) -> str | None:
    """Reklama bo'lsa sababini qaytaradi, aks holda None. Signal xabarlari bu yerga kelmaydi (ular tozalab nusxalanadi)."""
    m = AD_WORDS.search(text or "")
    if m:
        return f"reklama so'zi: {m.group(0).lower()}"
    if URL_RE.search(text or "") or has_link_entities:
        return "tashqi havola"
    if has_buttons:
        return "havolali tugma"
    return None


def invite_hash_from_link(link: str) -> str:
    match = re.search(r"(?:t\.me/\+|t\.me/joinchat/)([A-Za-z0-9_-]+)", link)
    if not match:
        raise ValueError("taklif havolasi noto'g'ri formatda")
    return match.group(1)


async def resolve_source(client, link: str, submit_join_request: bool):
    """Manba chat obyektini qaytaradi; admin tasdig'i kutilayotgan bo'lsa None."""
    from telethon import errors, types
    from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest

    if not re.search(r"t\.me/(\+|joinchat/)", link):  # ochiq kanal: @nom yoki t.me/nom
        return await client.get_entity(link)
    invite_hash = invite_hash_from_link(link)
    checked = await client(CheckChatInviteRequest(invite_hash))
    if isinstance(checked, types.ChatInviteAlready):
        return checked.chat
    request_needed = getattr(checked, "request_needed", False)
    if request_needed and not submit_join_request:
        raise RuntimeError("admin tasdig'i kerak (so'rov yuborilmadi)")
    try:
        updates = await client(ImportChatInviteRequest(invite_hash))
    except errors.InviteRequestSentError:
        return None
    except errors.UserAlreadyParticipantError:
        again = await client(CheckChatInviteRequest(invite_hash))
        if isinstance(again, types.ChatInviteAlready):
            return again.chat
        raise
    chats = getattr(updates, "chats", None) or []
    if not chats:
        raise RuntimeError("Telegram manba kanalni qaytarmadi")
    return chats[0]


async def copy_message(client, destination, message, source_chat_id: int, source_title: str,
                       store: MessageMapStore, chat_protected: bool = False, block_ads: bool = False):
    """Bitta xabarni nusxalaydi. Qaytaradi: manzil xabar ID yoki None (tashlab ketilgan)."""
    from telethon import errors, types

    from .parser import SignalError, parse_signal

    mid = message.id
    if chat_protected or getattr(message, "noforwards", False):
        log.warning("Himoyalangan xabar id=%s (%s): tashlab ketildi", mid, source_title)
        return None
    parent = None
    reply_to = getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None)
    if reply_to is not None:
        parent = store.get(source_chat_id, reply_to)
        if parent is None:
            log.info("Javob id=%s (%s): ota xabar nusxalanmagan, tashlab ketildi", mid, source_title)
            return None
    text, entities, media = message.message or "", message.entities or None, message.media
    if block_ads:
        try:
            is_signal = parse_signal(text) is not None
        except SignalError:
            is_signal = True  # chala signal ham signal: tozalab o'tkazamiz
        if is_signal:  # signal qoladi, ichidagi begona havola va "Открыть сделку" satri olib tashlanadi
            text, entities = clean_signal_text(text), None
        else:
            links = any(type(e).__name__ in ("MessageEntityTextUrl", "MessageEntityUrl") for e in (entities or []))
            reason = ad_reason(text, links, bool(getattr(message, "reply_markup", None)))
            if reason:
                log.info("Reklama filtri: id=%s (%s) o'tkazilmadi (%s)", mid, source_title, reason)
                return None

    async def send():
        if media and not isinstance(media, types.MessageMediaWebPage):
            return await client.send_file(destination, media, caption=text, formatting_entities=entities, reply_to=parent)
        if not text:
            return None
        return await client.send_message(destination, text, formatting_entities=entities, reply_to=parent, link_preview=True)

    try:
        try:
            copied = await send()
        except errors.FloodWaitError as e:  # Telegram "sekinroq" desa kutib, bir marta qayta urinamiz
            if e.seconds > MAX_FLOOD_WAIT:
                log.warning("FloodWait %ss, xabar id=%s (%s) tashlab ketildi", e.seconds, mid, source_title)
                return None
            log.info("FloodWait: %ss kutilmoqda", e.seconds)
            await asyncio.sleep(e.seconds + 1)
            copied = await send()
    except errors.ChatForwardsRestrictedError:
        log.warning("Telegram nusxalashni taqiqlaydi: id=%s (%s)", mid, source_title)
        return None
    except errors.RPCError as e:
        log.warning("Telegram rad etdi: id=%s (%s, %s)", mid, source_title, type(e).__name__)
        return None
    except Exception as e:  # noqa: BLE001 — bitta xabar xatosi botni to'xtatmasin
        log.error("Kutilmagan xato: id=%s (%s, %s)", mid, source_title, type(e).__name__)
        return None
    if isinstance(copied, (list, tuple)):
        copied = copied[0] if copied else None
    if copied is None or getattr(copied, "id", None) is None:
        log.warning("Nusxalanadigan matn/media yo'q yoki ID qaytmadi: id=%s (%s)", mid, source_title)
        return None
    store.put(source_chat_id, mid, copied.id)
    log.info("Nusxalandi: id=%s (%s) -> %s%s", mid, source_title, copied.id, f" (javob: {parent})" if parent else "")
    return copied.id


async def attach(client, fcfg: dict, db_path: Path) -> list[str]:
    """Manbalarga tinglovchilarni ulaydi. Qaytaradi: foydalanuvchiga ko'rsatiladigan holat satrlari."""
    from telethon import events

    report, sources = [], []
    for i, link in enumerate(fcfg.get("sources", []), 1):
        try:
            src = await resolve_source(client, link, submit_join_request=(link == fcfg.get("request_join")))
        except Exception as e:  # noqa: BLE001 — bitta manba ulanmasa qolganlari ishlayversin
            report.append(f"manba {i}: ulanmadi ({type(e).__name__}: {str(e)[:80]})")
            continue
        if src is None:
            report.append(f"manba {i}: qo'shilish so'rovi yuborildi, admin tasdig'i kutilmoqda (tasdiqlangach botni qayta ishga tushiring)")
            continue
        sources.append(src)
        report.append(f"manba {i}: {getattr(src, 'title', 'kanal')} ulandi")
    if not sources:
        return report + ["nusxalash yoqilmadi: birorta manba ulanmadi"]
    destination = await client.get_entity(fcfg["destination"])
    store = MessageMapStore(db_path)
    lock = asyncio.Lock()  # ota xabar javobdan oldin nusxalanib, yozib qo'yilishi uchun ketma-ket

    async def on_new(event) -> None:
        chat = event.chat
        title = getattr(chat, "title", "manba kanal")
        if event.chat_id is None:
            return
        media = type(event.message.media).__name__ if event.message.media else "yo'q"
        log.info("Yangi xabar id=%s (%s, media=%s)", event.message.id, title, media)
        async with lock:
            await copy_message(client, destination, event.message, event.chat_id, title, store,
                               chat_protected=bool(getattr(chat, "noforwards", False)),
                               block_ads=bool(fcfg.get("block_ads", True)))

    for src in sources:
        client.add_event_handler(on_new, events.NewMessage(chats=src))
    report.append(f"nusxalash yoqildi: {len(sources)} manba -> manzil kanal"
                  + (" (reklama filtri yoqilgan)" if fcfg.get("block_ads", True) else ""))
    return report
