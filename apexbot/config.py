"""Sozlamalar: settings.json (ochiq) + .env yoki muhit o'zgaruvchilari (maxfiy kalitlar)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("APEXBOT_HOME", Path(__file__).resolve().parent.parent))
LIVE_PHRASE = "ROZIMAN"

DEFAULTS = {
    "channels": ["@Apex_Trader_Uz"],
    "mode": "dry",               # dry | live
    "live_confirm": "",          # real rejim uchun aynan "ROZIMAN" yozilishi shart
    "testnet": False,
    "min_rr": 2.0,
    "size_mode": "margin_pct",   # margin_pct: balansning foizi marja sifatida | notional_pct | risk_pct
    "size_pct": 5.0,
    "leverage": 5,
    "max_leverage": 10,          # bundan katta leverage hech qachon qo'yilmaydi
    "margin_type": "ISOLATED",   # ISOLATED | CROSSED
    "tp_split": [50, 30, 20],
    "max_positions": 3,
    "entry_tolerance_pct": 0.5,  # narx entry'dan shuncha uzoqlashgan bo'lsa buyurtma berilmaydi
    "max_daily_loss_pct": 10.0,  # kunlik zarar balansning shu foizidan oshsa bot to'xtaydi
    "dry_balance": 1000.0,       # dry rejimda Binance'ga ulanib bo'lmasa ishlatiladigan shartli balans
    "notify": "me",
}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_settings(path: Path | None = None) -> dict:
    load_env(ROOT / ".env")
    cfg = dict(DEFAULTS)
    p = path or ROOT / "settings.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    if cfg["mode"] not in ("dry", "live"):
        raise ValueError("mode: dry yoki live")
    if cfg["mode"] == "live" and cfg.get("live_confirm") != LIVE_PHRASE:
        raise ValueError(f'Real rejim uchun settings.json da "live_confirm": "{LIVE_PHRASE}" bo\'lishi shart')
    if not 1 <= int(cfg["leverage"]) <= int(cfg["max_leverage"]):
        raise ValueError("leverage 1..max_leverage oralig'ida bo'lsin")
    if cfg["size_mode"] not in ("margin_pct", "notional_pct", "risk_pct"):
        raise ValueError("size_mode noto'g'ri")
    if not 0 < float(cfg["size_pct"]) <= 25:
        raise ValueError("size_pct 0..25 oralig'ida bo'lsin")
    if abs(sum(cfg["tp_split"]) - 100) > 1e-6 or any(x <= 0 for x in cfg["tp_split"]):
        raise ValueError("tp_split yig'indisi 100 bo'lsin")
    if cfg["margin_type"] not in ("ISOLATED", "CROSSED"):
        raise ValueError("margin_type: ISOLATED yoki CROSSED")


def secret(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        raise RuntimeError(f"{name} topilmadi (.env fayliga yozing)")
    return v


def is_live(cfg: dict) -> bool:
    return cfg["mode"] == "live" and cfg.get("live_confirm") == LIVE_PHRASE
