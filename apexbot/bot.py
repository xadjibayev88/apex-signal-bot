"""Telegram tinglovchi: kanal signallari -> Executor. Boshqaruv buyruqlari Saved Messages orqali.

Buyruqlar (o'zingizga, "Saved Messages" ga yozing):
  /status  holat     /stop  FAVQULODDA TO'XTATISH (hammasini yopadi)     /pause  yangi signal olmaslik
  /resume  davom     /help  yordam
Papkada STOP nomli fayl paydo bo'lsa ham favqulodda to'xtatish ishlaydi (Telegram ishlamay qolsa).
"""
from __future__ import annotations

import asyncio
import logging

from .config import ROOT, is_live, load_settings, secret
from .exchange import Binance
from .executor import Executor, Result
from .parser import SignalError, parse_signal, risk_reward
from .state import State

log = logging.getLogger("apexbot")


def fmt_result(sig, res: Result, cfg: dict) -> str:
    rr = risk_reward(sig)
    head = "✅ BUYURTMA" if res.ok and res.live else "🧪 DRY-RUN" if res.ok else "❌ RAD ETILDI"
    lines = [f"{head}: {sig.symbol} {sig.side}", f"Entry {sig.entry} | Stop {sig.stop} | R/R 1:{rr['rr']}",
             "Targetlar: " + ", ".join(str(t) for t in sig.targets)]
    if res.plan:
        p = res.plan
        lines += [f"Hajm: {p['qty']} ≈ {p['notional']:.2f} USDT (marja {p['margin']:.2f}, {p['leverage']}x {p['margin_type']})",
                  f"Stop urilsa: -{p['risk_usdt']:.2f} USDT ({p['risk_pct_balance']:.2f}% balans)",
                  "TP: " + ", ".join(f"{t} × {q}" for t, q in p["targets"])]
    lines.append(res.reason)
    return "\n".join(lines)


async def run() -> None:
    from telethon import TelegramClient, events  # faqat ishga tushganda kerak (testlar telethonsiz ishlaydi)

    cfg = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "bot.log", encoding="utf-8"), logging.StreamHandler()])
    logging.getLogger("telethon").setLevel(logging.ERROR)  # qayta ulanish haqidagi mayda xabarlar ekranni to'ldirmasin
    live = is_live(cfg)
    x = Binance(secret("BINANCE_API_KEY"), secret("BINANCE_API_SECRET"), cfg["testnet"]) if live else Binance(testnet=cfg["testnet"])
    state = State(ROOT / "state.json")
    ex = Executor(x, cfg, state)
    client = TelegramClient(str(ROOT / "session"), int(secret("TG_API_ID")), secret("TG_API_HASH"))
    lock = asyncio.Lock()

    async def notify(text: str) -> None:
        log.info(text.replace("\n", " | "))
        try:
            await client.send_message(cfg["notify"], text)
        except Exception as e:  # noqa: BLE001 — xabar yuborilmasa ham savdo mantig'i to'xtamasin
            log.error("Telegram xabari yuborilmadi: %s", type(e).__name__)

    async def emergency(source: str) -> None:
        async with lock:
            report = await asyncio.to_thread(ex.emergency_stop)
        await notify(f"🛑 FAVQULODDA TO'XTATISH ({source})\n" + "\n".join(report))

    @client.on(events.NewMessage(chats=cfg["channels"]))
    async def on_signal(event) -> None:
        key = f"{event.chat_id}:{event.message.id}"
        if state.seen(key):
            return
        state.mark(key)
        try:
            sig = parse_signal(event.message.message or "")
        except SignalError as e:
            await notify(f"⚠️ Signal noto'g'ri, buyurtma berilmadi: {e}")
            return
        if sig is None:
            return
        async with lock:  # signallar ketma-ket ishlanadi (limitlar aniq hisoblansin)
            res = await asyncio.to_thread(ex.handle, sig)
        await notify(fmt_result(sig, res, cfg))

    @client.on(events.NewMessage(chats="me", outgoing=True, pattern=r"^/(status|stop|pause|resume|help)\b"))
    async def on_command(event) -> None:
        cmd = event.pattern_match.group(1)
        if cmd == "stop":
            await emergency("/stop buyrug'i")
        elif cmd == "pause":
            state.set_paused(True)
            await notify("⏸ Pauza: yangi signallar olinmaydi (ochiq pozitsiyalar joyida).")
        elif cmd == "resume":
            state.set_paused(False)
            await notify("▶️ Bot davom etmoqda.")
        elif cmd == "status":
            lines = [f"Rejim: {'REAL' if live else 'DRY-RUN'} | {'pauza' if state.data['paused'] else 'ishlayapti'}",
                     f"Hajm: {cfg['size_pct']}% ({cfg['size_mode']}), {cfg['leverage']}x {cfg['margin_type']}, max {cfg['max_positions']} pozitsiya, min R/R 1:{cfg['min_rr']}"]
            if live:
                try:
                    bal, pos = await asyncio.to_thread(x.balance), await asyncio.to_thread(x.positions)
                    lines.append(f"Balans: {bal:.2f} USDT | ochiq pozitsiyalar: {len(pos)}")
                    lines += [f"  {p['symbol']} {p['positionAmt']} PnL {float(p['unRealizedProfit']):+.2f}" for p in pos]
                except Exception as e:  # noqa: BLE001
                    lines.append(f"Binance: {e}")
            await notify("\n".join(lines))
        else:
            await notify(__doc__.split("Buyruqlar", 1)[1].strip())

    async def watch_stop_file() -> None:
        flag = ROOT / "STOP"
        while True:
            if flag.exists():
                flag.rename(ROOT / "STOP.done")
                await emergency("STOP fayli")
            await asyncio.sleep(3)

    await client.start()
    if live:
        await asyncio.to_thread(x.sync_time)
    fwd = cfg.get("forwarder") or {}
    if fwd.get("enabled"):
        from . import forwarder
        try:
            lines = await forwarder.attach(client, fwd, ROOT / "message_map.sqlite3")
        except Exception as e:  # noqa: BLE001 — nusxalash ulanmasa ham signal boti ishlayversin
            lines = [f"nusxalash ulanmadi ({type(e).__name__})"]
        await notify("🔁 Nusxalash:\n" + "\n".join(lines))
    await notify(f"🤖 Apex signal bot ishga tushdi. Rejim: {'REAL' if live else 'DRY-RUN (pul ishlatilmaydi)'}. Kanal: {', '.join(cfg['channels'])}")
    asyncio.get_running_loop().create_task(watch_stop_file())
    await client.run_until_disconnected()


def single_instance():
    """Bir vaqtda faqat bitta bot: ikkinchisi sessiya faylini qulflab qo'yadi ("database is locked")."""
    import fcntl

    handle = open(ROOT / "bot.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Bot allaqachon ishlayapti (boshqa oynada yoki fonda). Bu nusxa ishga tushmadi.")
        raise SystemExit(3)
    return handle  # jarayon tugaguncha ochiq turadi


def main() -> None:
    lock = single_instance()
    try:
        asyncio.run(run())
    finally:
        lock.close()


if __name__ == "__main__":
    main()
