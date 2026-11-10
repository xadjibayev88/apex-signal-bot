#!/data/data/com.termux/files/usr/bin/bash
# Botni to'xtab qolsa qayta ishga tushiradigan halqa. To'xtatish: Volume Down + C
cd "$(dirname "$0")" || exit 1
command -v termux-wake-lock > /dev/null && termux-wake-lock
while true; do
  python -m apexbot
  [ $? -eq 3 ] && exit 0   # boshqa nusxa ishlayapti: bu halqa kerak emas
  echo "Bot to'xtadi ($(date)). 10 soniyadan keyin qayta ishga tushadi..."
  sleep 10
done
