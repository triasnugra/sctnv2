"""Tes scanner universe — semua jaringan dimock (tanpa akses internet)."""
import unittest

from src.data.fetch_ohlcv import DataFetchError, OHLCVFetcher
from src.data.universe import _is_excluded, resolve_universe


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def binance_payload():
    rows = [("BTCUSDT", 9e9), ("ETHUSDT", 5e9), ("USDCUSDT", 8e9), ("SOLUSDT", 3e9), ("BTCUPUSDT", 1e9), ("DOGEUSDT", 2e9),
            ("WBTCUSDT", 1e9), ("XRPUSDT", 2.5e9), ("PEPEUSDT", 1e9), ("TINYUSDT", 1e6), ("ETHBTC", 9e9), ("BNBUSDT", 1.5e9),
            ("FDUSDUSDT", 3e9), ("ADAUSDT", 9e8), ("SUIUSDT", 8e8), ("LINKUSDT", 7e8), ("AVAXUSDT", 6e8), ("TRXUSDT", 5e8)]
    return [{"symbol": s, "quoteVolume": str(v), "volume": "1"} for s, v in rows]


def cfg(**u):
    base = {"mode": "top_volume", "top_n": 5, "volume_sources": ["binance"], "min_quote_volume": 5e6}
    base.update(u)
    return {"benchmark": "BTC/USDT", "symbols": ["BTC/USDT", "ETH/USDT"], "universe": base}


class FakeEx:
    def __init__(self, tickers):
        self._t = tickers

    def fetch_tickers(self):
        return self._t


class TestUniverse(unittest.TestCase):
    def test_exclusions(self):
        for b in ("USDT", "USDC", "FDUSD", "WBTC", "STETH", "BTCUP", "ETHDOWN"):
            self.assertTrue(_is_excluded(b, set()), b)
        for b in ("BTC", "SUP", "ETH", "JUP", "PUMP", "DOWN"):   # koin asli tidak boleh ikut terbuang
            self.assertFalse(_is_excluded(b, set()), b)
        self.assertTrue(_is_excluded("TRUMP", {"TRUMP"}))

    def test_top_volume_binance(self):
        u = resolve_universe(cfg(), http_get=lambda url, **k: Resp(binance_payload()))
        self.assertEqual(u["symbols"], ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"])
        self.assertFalse(u["fallback"])
        self.assertEqual(u["source"], "binance")
        self.assertEqual([d["rank"] for d in u["detail"]], [1, 2, 3, 4, 5])

    def test_min_volume_filter(self):
        u = resolve_universe(cfg(top_n=30, min_quote_volume=1e9), http_get=lambda url, **k: Resp(binance_payload()))
        self.assertNotIn("TINY/USDT", u["symbols"])
        self.assertTrue(all(d["quote_volume"] >= 1e9 for d in u["detail"]))

    def test_binance_geoblock_falls_to_ccxt(self):
        tick = {"BTC/USDT": {"quoteVolume": 5e9}, "ETH/USDT": {"quoteVolume": 4e9}, "SOL/USDT": {"quoteVolume": 3e9},
                "XRP/USDT": {"quoteVolume": 2e9}, "ADA/USDT": {"baseVolume": 1e9, "last": 2.0},
                "BTC/USDT:USDT": {"quoteVolume": 9e11}, "ETH/BTC": {"quoteVolume": 9e11}}   # perp & non-USDT harus diabaikan
        u = resolve_universe(cfg(volume_sources=["binance", "ccxt:bitget"], top_n=4), http_get=lambda url, **k: Resp([], 451),
                             ccxt_factory=lambda ex_id: FakeEx(tick))
        self.assertEqual(u["source"], "ccxt:bitget")
        self.assertEqual(u["symbols"], ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"])
        self.assertEqual(u["data_provider_hint"], "ccxt:bitget")
        self.assertTrue(any("binance" in w for w in u["warnings"]))

    def test_all_sources_fail_falls_back_static(self):
        def boom(url, **k):
            raise ConnectionError("offline")
        u = resolve_universe(cfg(volume_sources=["binance", "ccxt:okx"]), http_get=boom,
                             ccxt_factory=lambda i: (_ for _ in ()).throw(RuntimeError("no net")))
        self.assertTrue(u["fallback"])
        self.assertEqual(u["symbols"], ["BTC/USDT", "ETH/USDT"])

    def test_static_mode_and_unknown_mode(self):
        self.assertEqual(resolve_universe(cfg(mode="static"))["symbols"], ["BTC/USDT", "ETH/USDT"])
        u = resolve_universe(cfg(mode="ngawur"))
        self.assertTrue(u["fallback"])

    def test_benchmark_always_included_and_first(self):
        payload = [r for r in binance_payload() if r["symbol"] != "BTCUSDT"]
        u = resolve_universe(cfg(top_n=4), http_get=lambda url, **k: Resp(payload))
        self.assertEqual(u["symbols"][0], "BTC/USDT")

    def test_marketcap_coingecko_maps_to_exchange(self):
        def get(url, **k):
            if "coingecko" in url:
                coins = ["btc", "eth", "usdt", "xrp", "bnb", "sol", "usdc", "steth", "doge", "ghostcoin", "ada"]   # ghostcoin tak ada di exchange
                return Resp([{"symbol": c, "market_cap_rank": i + 1} for i, c in enumerate(coins)])
            return Resp(binance_payload())
        u = resolve_universe(cfg(mode="top_marketcap", top_n=6), http_get=get)
        self.assertEqual(u["symbols"], ["BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT", "DOGE/USDT"])
        self.assertEqual(u["source"], "coingecko+binance")

    def test_marketcap_cmc_without_key_falls_to_coingecko(self):
        def get(url, **k):
            if "coingecko" in url:
                return Resp([{"symbol": c, "market_cap_rank": i + 1} for i, c in enumerate(["btc", "eth", "sol", "xrp", "doge", "ada"])])
            return Resp(binance_payload())
        u = resolve_universe(cfg(mode="top_marketcap", marketcap_source="cmc", top_n=5), http_get=get, env={})
        self.assertEqual(u["source"], "coingecko+binance")
        self.assertTrue(any("CMC" in w for w in u["warnings"]))

    def test_marketcap_cmc_with_key(self):
        seen = {}

        def get(url, **k):
            if "coinmarketcap" in url:
                seen["key"] = k["headers"]["X-CMC_PRO_API_KEY"]
                return Resp({"data": [{"symbol": s, "cmc_rank": i + 1} for i, s in enumerate(["BTC", "ETH", "USDT", "XRP", "SOL", "DOGE"])]})
            return Resp(binance_payload())
        u = resolve_universe(cfg(mode="top_marketcap", marketcap_source="cmc", top_n=5), http_get=get, env={"CMC_API_KEY": "abc"})
        self.assertEqual(seen["key"], "abc")
        self.assertEqual(u["symbols"], ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT"])
        self.assertEqual(u["source"], "cmc+binance")

    def test_marketcap_failure_falls_to_top_volume(self):
        def get(url, **k):
            if "coingecko" in url:
                raise ConnectionError("429")
            return Resp(binance_payload())
        u = resolve_universe(cfg(mode="top_marketcap", top_n=4), http_get=get)
        self.assertTrue(u["fallback"])
        self.assertEqual(u["symbols"][:2], ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(len(u["symbols"]), 4)


class TestFetcherDeadProvider(unittest.TestCase):
    def test_dead_provider_skipped_after_two_failures(self):
        class Dead:
            name = "dead"
            calls = 0

            def fetch(self, symbol, tf, limit):
                Dead.calls += 1
                raise DataFetchError("451")

        class Ok:
            name = "ok"

            def fetch(self, symbol, tf, limit):
                from src.data.synthetic import generate_15m
                import pandas as pd
                now = pd.Timestamp("2026-11-22 08:20", tz="UTC")
                return generate_15m(symbol, now).iloc[-limit:]
        f = OHLCVFetcher(["dead", "ok"], retries=1, backoff=0.0)
        f._providers = {"dead": Dead(), "ok": Ok()}
        import pandas as pd
        now = pd.Timestamp("2026-11-22 08:20", tz="UTC")
        for sym in ("A/USDT", "B/USDT", "C/USDT", "D/USDT"):
            out = f.fetch_symbol(sym, {"15m": 50}, now=now)
            self.assertIn("15m", out)
        self.assertEqual(Dead.calls, 2)        # setelah 2 kegagalan beruntun tidak dicoba lagi


if __name__ == "__main__":
    unittest.main()
