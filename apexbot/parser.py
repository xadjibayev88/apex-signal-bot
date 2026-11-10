"""Kanal xabaridan savdo signalini ajratish. Xabar ishonchsiz matn: faqat ticker/yo'nalish/narxlar o'qiladi."""
from __future__ import annotations

import re
from dataclasses import dataclass

NUM = r"(\d+(?:[.,]\d+)?)"


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str            # LONG | SHORT
    entry: float
    targets: tuple[float, ...]
    stop: float


class SignalError(ValueError):
    """Xabar signalga o'xshaydi, lekin noto'g'ri (buyurtma berilmaydi)."""


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_signal(text: str) -> Signal | None:
    """Signal bo'lmasa None; signal bo'lib, mantiqan xato bo'lsa SignalError.

    «Выделил» va «Общий капитал» satrlari ataylab o'qilmaydi (kanal muallifining hisobi).
    """
    if not text:
        return None
    # sarlavha: "$MASK -> LONG" yoki "📈 JTO LONG плечо x25" (xabardagi leverage ataylab o'qilmaydi)
    head = re.search(r"^\W*\$?([A-Z0-9]{2,15})\s*(?:->|→|—|-|:)?\s*(LONG|SHORT)\b", text, re.I | re.M)
    if not head:
        return None
    ticker, side = head.group(1).upper(), head.group(2).upper()
    entry = re.search(r"Точка\s+входа\s*:[^\d\n]*" + NUM, text, re.I)   # "0.3743" yoki "рынок (0.3388)"
    numbered = re.findall(r"Таргет\s*\d+\s*:\s*" + NUM, text, re.I)      # "Таргет 1: 0.3423" qatorlari
    targets = re.search(r"Таргеты?\s*:\s*([\d.,\s]+)", text, re.I)
    if numbered:
        targets = re.match(r"(.*)", ", ".join(numbered))
    stop = re.search(r"Стоп\s*:\s*" + NUM, text, re.I)
    if not (entry or targets or stop):
        return None  # "BTC LONG pozitsiyalar foydada" kabi oddiy matn: signal emas
    if not (entry and targets and stop):
        raise SignalError("signal to'liq emas (entry/target/stop yetishmaydi)")
    # "0.3781, 0.3820" -> vergul+bo'shliq ajratuvchi; "0,3781" o'nli vergul bo'lishi ham mumkin
    parts = [p for p in re.split(r"[;\s]+|,(?=\s)", targets.group(1).strip()) if p.strip(" ,")]
    tgs = tuple(_num(p.strip(" ,")) for p in parts)
    e, st = _num(entry.group(1)), _num(stop.group(1))
    if not tgs or e <= 0 or st <= 0 or any(t <= 0 for t in tgs):
        raise SignalError("narxlar noto'g'ri")
    if side == "LONG":
        if st >= e:
            raise SignalError("LONG, lekin stop >= entry")
        if any(t <= e for t in tgs):
            raise SignalError("LONG, lekin target <= entry")
        tgs = tuple(sorted(tgs))
    else:
        if st <= e:
            raise SignalError("SHORT, lekin stop <= entry")
        if any(t >= e for t in tgs):
            raise SignalError("SHORT, lekin target >= entry")
        tgs = tuple(sorted(tgs, reverse=True))
    return Signal(symbol=ticker + "USDT", side=side, entry=e, targets=tgs, stop=st)


def risk_reward(sig: Signal) -> dict:
    """R/R eng uzoq target bo'yicha (egasi belgilagan qoida)."""
    risk = abs(sig.entry - sig.stop)
    reward = abs(sig.targets[-1] - sig.entry)
    return {"risk_pct": round(risk / sig.entry * 100, 2), "reward_pct": round(reward / sig.entry * 100, 2),
            "rr": round(reward / risk, 2) if risk > 0 else 0.0}
