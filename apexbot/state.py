"""Diskdagi holat: ishlangan xabar ID lari, pauza, savdolar tarixi. Atomik yoziladi."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"processed": [], "paused": False, "trades": [], "day": "", "day_start_balance": None}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                path.rename(path.with_suffix(".broken"))

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def seen(self, key: str) -> bool:
        return key in self.data["processed"]

    def mark(self, key: str) -> None:
        self.data["processed"] = (self.data["processed"] + [key])[-2000:]
        self.save()

    def add_trade(self, trade: dict) -> None:
        self.data["trades"] = (self.data["trades"] + [{"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **trade}])[-500:]
        self.save()

    def set_paused(self, value: bool) -> None:
        self.data["paused"] = value
        self.save()

    def day_start(self, balance: float) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        if self.data["day"] != today or self.data["day_start_balance"] is None:
            self.data.update(day=today, day_start_balance=balance)
            self.save()
        return float(self.data["day_start_balance"])
