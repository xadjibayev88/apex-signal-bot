"""Internetsiz sinov: signal matnini o'qib, hozirgi sozlamalar bilan reja ko'rsatadi.

    python -m apexbot.dryrun                # namunaviy signal
    python -m apexbot.dryrun signal.txt     # fayldagi signal
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from .config import load_settings
from .parser import parse_signal, risk_reward
from .sizing import SymbolRules, position_qty, split_targets

SAMPLE = "$MASK -> LONG\nТочка входа: 0.3743\nТаргеты: 0.3781, 0.3820, 0.4039\nСтоп: 0.3605\nВыделил: 1200$\nОбщий капитал: 12766$"


def main() -> None:
    cfg = load_settings()
    text = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else SAMPLE
    sig = parse_signal(text)
    if sig is None:
        sys.exit("Signal topilmadi")
    rr = risk_reward(sig)
    rules = SymbolRules(Decimal("0.0001"), Decimal("1"), Decimal("1"), Decimal("5"))  # shartli qadamlar (birjasiz)
    bal = float(cfg["dry_balance"])
    qty = position_qty(sig, bal, cfg, rules)
    parts = split_targets(qty, len(sig.targets), cfg["tp_split"], rules, sig.entry)
    risk = abs(sig.entry - sig.stop) * float(qty)
    print(f"{sig.symbol} {sig.side} | entry {sig.entry} | stop {sig.stop} | R/R 1:{rr['rr']} ({'qabul' if rr['rr'] >= cfg['min_rr'] else 'RAD: min 1:' + str(cfg['min_rr'])})")
    print(f"Shartli balans {bal:.2f} USDT, {cfg['size_pct']}% {cfg['size_mode']}, {cfg['leverage']}x {cfg['margin_type']}")
    print(f"Hajm {qty} coin ≈ {float(qty) * sig.entry:.2f} USDT | marja ≈ {float(qty) * sig.entry / cfg['leverage']:.2f} USDT")
    print(f"Stop urilsa: -{risk:.2f} USDT ({risk / bal * 100:.2f}% balans)")
    for t, p in zip(sig.targets, parts):
        print(f"  TP {t}: {p} coin (+{abs(t - sig.entry) * float(p):.2f} USDT)")


if __name__ == "__main__":
    main()
