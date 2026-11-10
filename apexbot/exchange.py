"""Binance USDT-M Futures REST mijozi. Faqat standart kutubxona (Termux'da pandas/python-binance shart emas).

Kalitlar hech qachon logga yozilmaydi: xatolarda faqat Binance kodi va xabari qaytadi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from .sizing import SymbolRules, d

LIVE_URL = "https://fapi.binance.com"
TEST_URL = "https://testnet.binancefuture.com"


class ExchangeError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f"Binance xato {code}: {msg}")
        self.code = code


class Binance:
    def __init__(self, key: str = "", secret: str = "", testnet: bool = False, timeout: int = 15):
        self._key, self._secret = key, secret.encode()
        self.base = TEST_URL if testnet else LIVE_URL
        self.timeout = timeout
        self._rules: dict[str, SymbolRules] = {}
        self._offset = 0

    # ---- past daraja
    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._offset
            params["recvWindow"] = 5000
            q = urllib.parse.urlencode(params)
            q += "&signature=" + hmac.new(self._secret, q.encode(), hashlib.sha256).hexdigest()
        else:
            q = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{self.base}{path}?{q}", method=method)
        if self._key:
            req.add_header("X-MBX-APIKEY", self._key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
                raise ExchangeError(body.get("code", e.code), body.get("msg", "")) from None
            except (ValueError, AttributeError):
                raise ExchangeError(e.code, "HTTP xato") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ExchangeError("NET", type(e).__name__) from None

    def sync_time(self) -> None:
        self._offset = int(self._request("GET", "/fapi/v1/time")["serverTime"]) - int(time.time() * 1000)

    # ---- ochiq ma'lumot
    def rules(self, symbol: str) -> SymbolRules | None:
        if not self._rules:
            for s in self._request("GET", "/fapi/v1/exchangeInfo")["symbols"]:
                if s.get("status") != "TRADING" or s.get("contractType") != "PERPETUAL":
                    continue
                f = {x["filterType"]: x for x in s["filters"]}
                self._rules[s["symbol"]] = SymbolRules(
                    tick=d(f["PRICE_FILTER"]["tickSize"]), step=d(f["LOT_SIZE"]["stepSize"]),
                    min_qty=d(f["LOT_SIZE"]["minQty"]), min_notional=d(f.get("MIN_NOTIONAL", {}).get("notional", "5")))
        return self._rules.get(symbol)

    def mark_price(self, symbol: str) -> float:
        return float(self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})["markPrice"])

    # ---- hisob
    def balance(self) -> float:
        for a in self._request("GET", "/fapi/v2/balance", signed=True):
            if a["asset"] == "USDT":
                return float(a["availableBalance"])
        return 0.0

    def hedge_mode(self) -> bool:
        return bool(self._request("GET", "/fapi/v1/positionSide/dual", signed=True)["dualSidePosition"])

    def positions(self) -> list[dict]:
        return [p for p in self._request("GET", "/fapi/v2/positionRisk", signed=True) if float(p["positionAmt"]) != 0]

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)

    def set_margin_type(self, symbol: str, margin_type: str) -> None:
        try:
            self._request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}, signed=True)
        except ExchangeError as e:
            if e.code != -4046:  # "No need to change margin type"
                raise

    # ---- buyurtmalar
    def market(self, symbol: str, side: str, qty: Decimal, reduce_only: bool = False) -> dict:
        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": format(qty, "f"),
            "reduceOnly": "true" if reduce_only else None, "newOrderRespType": "RESULT"}, signed=True)

    def conditional(self, symbol: str, side: str, kind: str, trigger: Decimal,
                    qty: Decimal | None = None, close_position: bool = False) -> dict:
        """STOP_MARKET / TAKE_PROFIT_MARKET. Avval yangi Algo Order API, ishlamasa eski endpoint."""
        common = {"symbol": symbol, "side": side, "type": kind, "workingType": "MARK_PRICE",
                  "closePosition": "true" if close_position else None,
                  "quantity": None if close_position else format(qty, "f"),
                  "reduceOnly": None if close_position else "true"}
        try:
            return self._request("POST", "/fapi/v1/algoOrder",
                                 {**common, "algoType": "CONDITIONAL", "triggerPrice": format(trigger, "f")}, signed=True)
        except ExchangeError as algo_err:
            if algo_err.code == "NET":
                raise
            try:
                return self._request("POST", "/fapi/v1/order", {**common, "stopPrice": format(trigger, "f")}, signed=True)
            except ExchangeError as legacy_err:
                raise ExchangeError(legacy_err.code, f"{legacy_err} (algo: {algo_err})") from None

    def cancel_all(self, symbol: str) -> None:
        errors = []
        for method, path in (("DELETE", "/fapi/v1/allOpenOrders"), ("DELETE", "/fapi/v1/algoOpenOrders")):
            try:
                self._request(method, path, {"symbol": symbol}, signed=True)
            except ExchangeError as e:
                errors.append(e)
        if len(errors) == 2:
            raise errors[0]

    def open_order_symbols(self) -> set[str]:
        return {o["symbol"] for o in self._request("GET", "/fapi/v1/openOrders", signed=True)}
