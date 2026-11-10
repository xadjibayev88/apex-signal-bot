"""Pozitsiya hajmi, birja qadamlariga yaxlitlash va targetlar bo'yicha taqsimlash (Decimal bilan, aniq)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from .parser import Signal


@dataclass(frozen=True)
class SymbolRules:
    tick: Decimal        # narx qadami
    step: Decimal        # miqdor qadami
    min_qty: Decimal
    min_notional: Decimal


class SizeError(ValueError):
    pass


def d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def round_tick(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def position_qty(sig: Signal, balance: float, cfg: dict, rules: SymbolRules, price: float | None = None) -> Decimal:
    """Umumiy miqdor (coin). balance — foydalanuvchining O'Z Binance balansi (signaldagi «капитал» emas)."""
    px, bal, pct, lev = d(price or sig.entry), d(balance), d(cfg["size_pct"]) / 100, d(cfg["leverage"])
    mode = cfg["size_mode"]
    if mode == "margin_pct":        # balansning X% marja -> pozitsiya = marja * leverage
        notional = bal * pct * lev
    elif mode == "notional_pct":    # pozitsiyaning umumiy hajmi balansning X%
        notional = bal * pct
    else:                           # risk_pct: stop urilsa balansning X% yo'qoladi
        risk_per_coin = abs(d(sig.entry) - d(sig.stop))
        notional = (bal * pct / risk_per_coin) * px
        notional = min(notional, bal * lev * d("0.95"))  # marja yetadigan chegaradan oshmasin
    qty = floor_step(notional / px, rules.step)
    if qty < rules.min_qty or qty * px < rules.min_notional:
        raise SizeError(f"hajm juda kichik: {qty} (min notional {rules.min_notional})")
    return qty


def split_targets(qty: Decimal, n_targets: int, split: list, rules: SymbolRules, price: float) -> list[Decimal]:
    """Miqdorni targetlarga bo'lish. Target soni taqsimotdan kam/ko'p bo'lsa moslanadi; qoldiq oxirgisiga."""
    shares = [d(s) for s in split[:n_targets]]
    if n_targets > len(shares):
        shares += [shares[-1]] * (n_targets - len(shares))
    total = sum(shares)
    parts = [floor_step(qty * s / total, rules.step) for s in shares]
    parts[-1] += qty - sum(parts)
    # juda kichik bo'laklar (min_qty/min_notional dan past) keyingi bo'lakka qo'shiladi
    out: list[Decimal] = []
    carry = Decimal(0)
    for p in parts:
        p += carry
        if p < rules.min_qty or p * d(price) < rules.min_notional:
            carry = p
            out.append(Decimal(0))
        else:
            carry = Decimal(0)
            out.append(p)
    if carry and any(out):
        last = max(i for i, p in enumerate(out) if p)
        out[last] += carry
    elif carry:
        out[-1] = carry
    return out
