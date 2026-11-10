"""Signalni buyurtmaga aylantirish. Barcha "BERMA" qoidalari shu yerda; dry rejimda birjaga hech narsa yuborilmaydi."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from .config import is_live
from .exchange import ExchangeError
from .parser import Signal, risk_reward
from .sizing import SizeError, d, position_qty, round_tick, split_targets

log = logging.getLogger("apexbot")


@dataclass
class Result:
    ok: bool
    reason: str = ""
    plan: dict = field(default_factory=dict)
    live: bool = False


class Executor:
    def __init__(self, exchange, cfg: dict, state):
        self.x, self.cfg, self.state = exchange, cfg, state

    # ---- reja (dry va live uchun bir xil hisob)
    def plan(self, sig: Signal, balance: float, price: float) -> dict:
        rules = self.x.rules(sig.symbol)
        if rules is None:
            raise SizeError(f"{sig.symbol} Binance Futures'da yo'q")
        qty = position_qty(sig, balance, self.cfg, rules, price)
        parts = split_targets(qty, len(sig.targets), self.cfg["tp_split"], rules, price)
        risk = abs(d(price) - d(sig.stop)) * qty
        return {"symbol": sig.symbol, "side": sig.side, "qty": qty, "price": price,
                "notional": float(qty * d(price)), "margin": float(qty * d(price) / d(self.cfg["leverage"])),
                "leverage": int(self.cfg["leverage"]), "margin_type": self.cfg["margin_type"],
                "stop": round_tick(d(sig.stop), rules.tick),
                "targets": [(round_tick(d(t), rules.tick), p) for t, p in zip(sig.targets, parts) if p > 0],
                "risk_usdt": float(risk), "risk_pct_balance": float(risk / d(balance) * 100) if balance else 0.0}

    def check(self, sig: Signal, price: float, balance: float, open_symbols: set[str]) -> str:
        """Bo'sh satr = ruxsat; aks holda rad etish sababi."""
        cfg = self.cfg
        if self.state.data["paused"]:
            return "bot pauzada (/resume bilan yoqiladi)"
        rr = risk_reward(sig)["rr"]
        if rr < cfg["min_rr"]:
            return f"R/R 1:{rr} < 1:{cfg['min_rr']}"
        if sig.symbol in open_symbols:
            return f"{sig.symbol} bo'yicha pozitsiya/buyurtma allaqachon bor"
        if len(open_symbols) >= cfg["max_positions"]:
            return f"ochiq pozitsiyalar limiti ({cfg['max_positions']})"
        drift = (price - sig.entry) / sig.entry * 100
        if abs(drift) > cfg["entry_tolerance_pct"]:
            return f"narx entry'dan {drift:+.2f}% uzoqda (limit {cfg['entry_tolerance_pct']}%)"
        if (sig.side == "LONG" and price <= sig.stop) or (sig.side == "SHORT" and price >= sig.stop):
            return "narx stop darajasidan o'tib ketgan"
        if balance <= 0:
            return "balans yo'q"
        start = self.state.day_start(balance)
        if start and (start - balance) / start * 100 >= cfg["max_daily_loss_pct"]:
            self.state.set_paused(True)
            return f"kunlik zarar limiti ({cfg['max_daily_loss_pct']}%) — bot pauzaga o'tdi"
        return ""

    def handle(self, sig: Signal) -> Result:
        live = is_live(self.cfg)
        try:
            price = self.x.mark_price(sig.symbol)
            if live:
                if self.x.hedge_mode():
                    return Result(False, "Binance'da Hedge Mode yoqilgan — One-way Mode'ga o'tkazing", live=live)
                balance = self.x.balance()
                open_symbols = {p["symbol"] for p in self.x.positions()} | self.x.open_order_symbols()
            else:
                balance = float(self.cfg["dry_balance"])
                open_symbols = {t["symbol"] for t in self.state.data["trades"][-self.cfg["max_positions"]:] if t.get("open")}
            reason = self.check(sig, price, balance, open_symbols)
            if reason:
                return Result(False, reason, live=live)
            plan = self.plan(sig, balance, price)
        except (ExchangeError, SizeError) as e:
            return Result(False, str(e), live=live)
        if not live:
            self.state.add_trade({"symbol": sig.symbol, "side": sig.side, "dry": True, "open": False,
                                  "qty": str(plan["qty"]), "price": price})
            return Result(True, "DRY-RUN: buyurtma yuborilmadi", plan, live=False)
        return self._execute(sig, plan)

    # ---- real buyurtma
    def _execute(self, sig: Signal, plan: dict) -> Result:
        sym, qty = plan["symbol"], plan["qty"]
        buy, sell = ("BUY", "SELL") if sig.side == "LONG" else ("SELL", "BUY")
        try:
            self.x.set_margin_type(sym, plan["margin_type"])
            self.x.set_leverage(sym, plan["leverage"])
            self.x.market(sym, buy, qty)
        except ExchangeError as e:
            return Result(False, f"pozitsiya ochilmadi: {e}", plan, live=True)
        try:  # stop-loss qo'yilmasa pozitsiya darhol yopiladi
            self.x.conditional(sym, sell, "STOP_MARKET", plan["stop"], close_position=True)
        except ExchangeError as e:
            closed = self._flatten(sym, sell, qty)
            return Result(False, f"stop-loss qo'yilmadi ({e}); pozitsiya {'yopildi' if closed else 'YOPILMADI — QO‘LDA YOPING'}", plan, live=True)
        tp_errors = []
        last = len(plan["targets"]) - 1
        for i, (tp, part) in enumerate(plan["targets"]):
            try:
                self.x.conditional(sym, sell, "TAKE_PROFIT_MARKET", tp, qty=part, close_position=(i == last))
            except ExchangeError as e:
                tp_errors.append(f"TP{i + 1}: {e}")
        self.state.add_trade({"symbol": sym, "side": sig.side, "dry": False, "open": True, "qty": str(qty), "price": plan["price"]})
        note = "ochildi, stop va targetlar qo'yildi" if not tp_errors else "ochildi, stop qo'yildi, lekin: " + "; ".join(tp_errors)
        return Result(True, note, plan, live=True)

    def _flatten(self, symbol: str, close_side: str, qty: Decimal) -> bool:
        for _ in range(3):
            try:
                self.x.market(symbol, close_side, qty, reduce_only=True)
                return True
            except ExchangeError as e:
                log.error("Yopishda xato: %s", e)
        return False

    def emergency_stop(self) -> list[str]:
        """Barcha buyurtmalarni bekor qiladi, barcha pozitsiyalarni yopadi va botni pauzaga qo'yadi."""
        self.state.set_paused(True)
        if not is_live(self.cfg):
            return ["bot pauzada (dry rejim: birjada ochiq buyurtma yo'q)"]
        report = []
        try:
            symbols = self.x.open_order_symbols()
            positions = self.x.positions()
        except ExchangeError as e:
            return [f"Binance'ga ulanib bo'lmadi: {e}. Ilovadan qo'lda yoping."]
        for s in symbols | {p["symbol"] for p in positions}:
            try:
                self.x.cancel_all(s)
                report.append(f"{s}: buyurtmalar bekor qilindi")
            except ExchangeError as e:
                report.append(f"{s}: bekor qilishda xato ({e})")
        for p in positions:
            amt = d(p["positionAmt"])
            ok = self._flatten(p["symbol"], "SELL" if amt > 0 else "BUY", abs(amt))
            report.append(f"{p['symbol']}: pozitsiya {'yopildi' if ok else 'YOPILMADI — qo‘lda yoping'}")
        return report or ["ochiq buyurtma va pozitsiya yo'q; bot pauzada"]
