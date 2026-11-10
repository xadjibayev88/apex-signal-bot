"""Nusxalash (forwarder) sozlamalarini savol-javob bilan settings.json ga yozadi (qo'lda JSON tahrirlash shart emas).

    python -m apexbot.setup_forwarder
Havolalar faqat telefoningizdagi settings.json da saqlanadi (GitHub'ga yuklanmaydi).
"""
from __future__ import annotations

import json

from .config import DEFAULTS, ROOT


def main() -> None:
    path = ROOT / "settings.json"
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(DEFAULTS)
    print("Manba kanallar havolalarini bittadan kiriting (t.me/+... yoki @kanal). Tugatish uchun bo'sh Enter.")
    sources = []
    while True:
        link = input(f"Manba {len(sources) + 1}: ").strip()
        if not link:
            break
        sources.append(link)
    if not sources:
        cfg["forwarder"] = {"enabled": False}
        print("Manba kiritilmadi: nusxalash o'chirildi.")
    else:
        dest = input("Manzil kanal (masalan @kanalim): ").strip()
        req = input("Admin tasdig'i kerak bo'lgan manba raqami (yo'q bo'lsa bo'sh Enter): ").strip()
        request_join = sources[int(req) - 1] if req.isdigit() and 1 <= int(req) <= len(sources) else ""
        cfg["forwarder"] = {"enabled": True, "sources": sources, "request_join": request_join, "destination": dest}
        print(f"Saqlandi: {len(sources)} manba -> {dest}")
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
