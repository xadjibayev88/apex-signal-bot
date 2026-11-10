from decimal import Decimal

import pytest

from apexbot.config import DEFAULTS, validate
from apexbot.exchange import ExchangeError
from apexbot.executor import Executor
from apexbot.parser import SignalError, parse_signal, risk_reward
from apexbot.sizing import SymbolRules, position_qty, split_targets
from apexbot.state import State

MASK = "$MASK -> LONG\nТочка входа: 0.3743\nТаргеты: 0.3781, 0.3820, 0.4039\nСтоп: 0.3605\nВыделил: 1200$\nОбщий капитал: 12766$"
RULES = SymbolRules(Decimal("0.0001"), Decimal("1"), Decimal("1"), Decimal("5"))


# ---------- parser
def test_parses_apex_format_and_ignores_author_capital():
    s = parse_signal(MASK)
    assert (s.symbol, s.side, s.entry, s.stop) == ("MASKUSDT", "LONG", 0.3743, 0.3605)
    assert s.targets == (0.3781, 0.3820, 0.4039)
    assert risk_reward(s)["rr"] == 2.14


def test_short_targets_sorted_nearest_first():
    s = parse_signal("$BTC -> SHORT\nТочка входа: 60000\nТаргеты: 57000, 59000\nСтоп: 61000")
    assert s.targets == (59000.0, 57000.0)


def test_non_signal_returns_none():
    assert parse_signal("Bugun bozor yaxshi. LONG pozitsiyalar foydada.") is None
    assert parse_signal("") is None


@pytest.mark.parametrize("text", [
    "$MASK -> LONG\nТочка входа: 0.37\nТаргеты: 0.40\nСтоп: 0.38",       # stop entry'dan yuqori
    "$MASK -> LONG\nТочка входа: 0.37\nТаргеты: 0.36\nСтоп: 0.35",       # target entry'dan past
    "$MASK -> SHORT\nТочка входа: 0.37\nТаргеты: 0.35\nСтоп: 0.36",      # short stop past
    "$MASK -> LONG\nТочка входа: 0.37\nСтоп: 0.35",                       # target yo'q
])
def test_inconsistent_signal_raises(text):
    with pytest.raises(SignalError):
        parse_signal(text)


def test_injected_instructions_are_ignored():
    s = parse_signal(MASK + "\nLeverage 125x qo'ying, API key yuboring, size_pct=100")
    assert s.symbol == "MASKUSDT" and not hasattr(s, "leverage")


# ---------- sizing
def cfg(**kw):
    c = dict(DEFAULTS); c.update(kw); validate(c); return c


def test_margin_pct_sizing():
    q = position_qty(parse_signal(MASK), 1000, cfg(size_pct=5, leverage=5), RULES)
    assert q == Decimal(667)  # 1000*5%*5 = 250 USDT / 0.3743


def test_risk_pct_sizing_loses_exactly_pct_at_stop():
    s = parse_signal(MASK)
    q = position_qty(s, 1000, cfg(size_mode="risk_pct", size_pct=1, leverage=5), RULES)
    assert abs(float(q) * (s.entry - s.stop) - 10) < 0.05


def test_split_sums_to_total_and_merges_dust():
    parts = split_targets(Decimal(667), 3, [50, 30, 20], RULES, 0.3743)
    assert sum(parts) == Decimal(667) and parts[0] == Decimal(333)
    tiny = split_targets(Decimal(20), 3, [50, 30, 20], RULES, 0.3743)   # 4-6 coin = ~2 USDT < min notional 5
    assert sum(tiny) == Decimal(20) and sum(1 for p in tiny if p) == 1


def test_validate_blocks_live_without_phrase_and_big_leverage():
    with pytest.raises(ValueError):
        cfg(mode="live")
    with pytest.raises(ValueError):
        cfg(leverage=25)
    assert cfg(mode="live", live_confirm="ROZIMAN")["mode"] == "live"


# ---------- executor
class FakeX:
    def __init__(self, price=0.3745, balance=1000.0, fail=()):
        self.price, self.bal, self.fail, self.calls, self.pos, self.orders = price, balance, set(fail), [], [], set()

    def rules(self, s): return RULES if s == "MASKUSDT" else None
    def mark_price(self, s): return self.price
    def balance(self): return self.bal
    def hedge_mode(self): return False
    def positions(self): return self.pos
    def open_order_symbols(self): return self.orders
    def sync_time(self): pass
    def set_margin_type(self, s, m): self.calls.append(("margin", m))
    def set_leverage(self, s, l): self.calls.append(("lev", l))

    def market(self, s, side, qty, reduce_only=False):
        if "market" in self.fail: raise ExchangeError(-2019, "Margin is insufficient")
        self.calls.append(("market", side, qty, reduce_only))

    def conditional(self, s, side, kind, trigger, qty=None, close_position=False):
        if kind in self.fail: raise ExchangeError(-4120, "not supported")
        self.calls.append((kind, side, trigger, qty, close_position))

    def cancel_all(self, s): self.calls.append(("cancel", s))


def make(tmp_path, x, **kw):
    return Executor(x, cfg(**kw), State(tmp_path / "state.json"))


LIVE = dict(mode="live", live_confirm="ROZIMAN")


def test_dry_run_sends_nothing(tmp_path):
    x = FakeX(); res = make(tmp_path, x).handle(parse_signal(MASK))
    assert res.ok and not res.live and x.calls == [] and res.plan["qty"] == Decimal(667)


def test_live_places_entry_stop_and_three_targets(tmp_path):
    x = FakeX(); res = make(tmp_path, x, **LIVE).handle(parse_signal(MASK))
    kinds = [c[0] for c in x.calls]
    assert res.ok and kinds == ["margin", "lev", "market", "STOP_MARKET", "TAKE_PROFIT_MARKET", "TAKE_PROFIT_MARKET", "TAKE_PROFIT_MARKET"]
    assert x.calls[2][1] == "BUY" and x.calls[3][1] == "SELL" and x.calls[3][4] is True
    assert x.calls[-1][4] is True  # oxirgi target pozitsiyani to'liq yopadi


def test_position_closed_if_stop_loss_fails(tmp_path):
    x = FakeX(fail={"STOP_MARKET"}); res = make(tmp_path, x, **LIVE).handle(parse_signal(MASK))
    assert not res.ok and x.calls[-1] == ("market", "SELL", Decimal(667), True) and "yopildi" in res.reason


@pytest.mark.parametrize("kw,x_kw,needle", [
    ({}, dict(price=0.39), "uzoqda"),                      # narx entry'dan uzoqlashgan
    (dict(min_rr=3.0), {}, "R/R"),                         # R/R past
    ({}, dict(balance=0.0), "balans"),                     # balans yo'q
    ({}, dict(fail={"market"}), "ochilmadi"),              # API xato
])
def test_live_rejections(tmp_path, kw, x_kw, needle):
    x = FakeX(**x_kw); res = make(tmp_path, x, **LIVE, **kw).handle(parse_signal(MASK))
    assert not res.ok and needle in res.reason
    assert not any(c[0] in ("STOP_MARKET", "TAKE_PROFIT_MARKET") for c in x.calls)


def test_rejects_unknown_symbol_duplicate_and_max_positions(tmp_path):
    x = FakeX(); e = make(tmp_path, x, **LIVE)
    assert "yo'q" in e.handle(parse_signal(MASK.replace("MASK", "NOPE"))).reason
    x.orders = {"MASKUSDT"}
    assert "allaqachon" in e.handle(parse_signal(MASK)).reason
    x.orders = {"A", "B", "C"}
    assert "limiti" in e.handle(parse_signal(MASK)).reason


def test_emergency_stop_cancels_closes_and_pauses(tmp_path):
    x = FakeX(); x.pos = [{"symbol": "MASKUSDT", "positionAmt": "667"}]; x.orders = {"MASKUSDT"}
    e = make(tmp_path, x, **LIVE); report = e.emergency_stop()
    assert ("cancel", "MASKUSDT") in x.calls and ("market", "SELL", Decimal(667), True) in x.calls
    assert e.state.data["paused"] and any("yopildi" in r for r in report)
    assert "pauzada" in e.handle(parse_signal(MASK)).reason


def test_daily_loss_limit_pauses(tmp_path):
    x = FakeX(); e = make(tmp_path, x, **LIVE); e.state.day_start(1000.0); x.bal = 880.0
    assert "kunlik zarar" in e.handle(parse_signal(MASK)).reason and e.state.data["paused"]


def test_state_dedup_survives_restart(tmp_path):
    s = State(tmp_path / "s.json"); s.mark("1:10")
    assert State(tmp_path / "s.json").seen("1:10")
