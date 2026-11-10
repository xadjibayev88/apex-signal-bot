# Apex signal bot

Telegram kanalidagi (`@Apex_Trader_Uz`) savdo signallarini o'qib, Binance **USDT-M Futures** da buyurtma ochadi.
**Standart holatda DRY-RUN**: pul ishlatilmaydi, bot faqat hisob-kitobni Saved Messages ga yuboradi.

## Nima qiladi
- Signalni o'qiydi: ticker, LONG/SHORT, entry, barcha targetlar, stop. `Выделил` va `Общий капитал` o'qilmaydi.
- Tekshiradi: signal to'liqmi, yo'nalish mosmi, R/R ≥ 1:2 (eng uzoq target bo'yicha), ticker Futures'da bormi,
  narx entry'dan uzoqlashmaganmi, ochiq pozitsiyalar limiti, kunlik zarar limiti.
- Real rejimda: market bilan kiradi → stop-loss qo'yadi → targetlarga taqsimlab take-profit qo'yadi.
  **Stop-loss qo'yilmasa pozitsiya darhol yopiladi.**
- Har bir natija (qabul / rad / xato) Saved Messages ga keladi. API kalitlar hech qayerga yozilmaydi.

## Termux'da o'rnatish
```
pkg install git python
git clone https://github.com/xadjibayev88/apex-signal-bot
cd apex-signal-bot
pip install telethon
cp .env.example .env
cp settings.example.json settings.json
nano .env          # TG_API_ID va TG_API_HASH ni yozing. Saqlash: Volume Down + X, keyin Y, Enter
python -m apexbot.dryrun     # internetsiz sinov: namunaviy signal bo'yicha hisob
./run.sh                     # botni ishga tushirish (birinchi marta telefon raqam va kod so'raydi)
```
Bot fonda ishlashi uchun Termux bildirishnomasidagi **Acquire wakelock** yoqilgan bo'lsin (run.sh o'zi yoqadi)
va telefon sozlamalarida Termux uchun batareya tejash o'chirilsin.

## Boshqarish (Telegram → Saved Messages ga yozing)
| Buyruq | Nima qiladi |
|---|---|
| `/status` | rejim, sozlamalar, balans va ochiq pozitsiyalar |
| `/stop` | **favqulodda to'xtatish**: barcha buyurtmalarni bekor qiladi, pozitsiyalarni yopadi, botni pauzaga qo'yadi |
| `/pause` | yangi signal olmaydi (ochiq pozitsiyalar qoladi) |
| `/resume` | davom ettiradi |

Telegram ishlamasa: Termux'da bot papkasida `touch STOP` — xuddi `/stop` kabi ishlaydi.

## Boshqa kanallardan nusxalash (ixtiyoriy)
Bot signal kuzatish bilan birga, siz a'zo bo'lgan manba kanallardagi **yangi** xabarlarni o'z kanalingizga nusxalashi
ham mumkin (forward emas; javoblar mos ota xabarga ulanadi; himoyalangan postlar tashlab ketiladi). Ikkalasi bitta
Telegram ulanishida ishlaydi, shuning uchun alohida skript va alohida sessiya kerak emas.
```
python -m apexbot.setup_forwarder    # havolalar va manzil kanalni so'raydi, settings.json ga yozadi
./run.sh
```
Havolalar faqat telefondagi `settings.json` da turadi. O'chirish: `setup_forwarder` ni ishga tushirib, birinchi savolga bo'sh Enter.
Eski javob bog'lanishlarini saqlash uchun: `cp ~/telegram-forwarder/telegram_message_map.sqlite3 message_map.sqlite3`.

## Sozlamalar (`settings.json`)
| Kalit | Ma'nosi | Standart |
|---|---|---|
| `size_mode` | `margin_pct` — balansning foizi marja sifatida; `notional_pct` — pozitsiya hajmi balansning foizi; `risk_pct` — stop urilsa balansning shu foizi yo'qoladi | `margin_pct` |
| `size_pct` | yuqoridagi foiz | 5 |
| `leverage`, `max_leverage` | yelka; `max_leverage` dan katta qo'yib bo'lmaydi | 5, 10 |
| `margin_type` | `ISOLATED` yoki `CROSSED` | `ISOLATED` |
| `tp_split` | targetlar bo'yicha taqsimot, yig'indisi 100 | 50/30/20 |
| `max_positions` | bir vaqtda ochiq pozitsiyalar | 3 |
| `min_rr` | minimal R/R | 2.0 |
| `entry_tolerance_pct` | narx entry'dan shuncha foiz uzoqlashsa kirmaydi | 0.5 |
| `max_daily_loss_pct` | kunlik zarar shu foizdan oshsa bot pauzaga o'tadi | 10 |

## Real rejimga o'tish
1. Bir necha kun dry-run natijalarini kuzating.
2. Binance → API Management → yangi kalit: **Enable Futures** yoqilgan, **Enable Withdrawals O'CHIQ**, imkon bo'lsa IP cheklovi.
   Binance Futures'da **One-way Mode** bo'lsin (Hedge Mode'da bot savdo qilmaydi).
3. Kalitlarni faqat `.env` ga yozing (chatga, kodga, GitHub'ga emas).
4. `settings.json` da `"mode": "live"` va `"live_confirm": "ROZIMAN"` — ikkalasi bo'lmasa bot real rejimda ishga tushmaydi.
5. Avval `"testnet": true` bilan Binance Futures Testnet kalitida sinab ko'rish tavsiya etiladi.

## Cheklovlar (halol ro'yxat)
- Binance so'rovlari haqiqiy birjada hali sinalmagan (ishlab chiqilgan muhitdan Binance ochilmadi); mantiq soxta birja
  bilan 23 ta testda tekshirilgan. Shu sabab birinchi real sinov testnet yoki eng kichik hajm bilan bo'lsin.
- Bot telefon yoki server yoniq va internetda bo'lgandagina ishlaydi. GitHub Actions bunga yaramaydi:
  u doimiy tinglay olmaydi va Binance AQSh serverlaridan kelgan so'rovlarni bloklaydi.
- Kirish market buyurtma bilan: tez harakatda narx biroz farq qilishi mumkin (`entry_tolerance_pct` bilan cheklangan).
- Bu moliyaviy maslahat emas. Futures savdosida pulni to'liq yo'qotish mumkin.
