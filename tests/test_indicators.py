"""Tes indikator grafik (MACD, RSI, Supertrend, UTCS, EMA), key levels gaya Spaceman, dan ekspor data chart."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.chart_indicators import add_indicators
from src.analysis.key_levels import compute_key_levels
from src.config_loader import load_config
from src.data.indicators import ema, macd, rsi, supertrend, utcs
from src.data.synthetic import DemoSource
from src.models import MondayRange


def walk(n=400, seed=3, freq="1h", start="2026-01-01", vol=0.01):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.004, "low": np.minimum(o, c) * 0.996, "close": c,
                         "volume": rng.lognormal(5, 0.4, n)}, index=idx)


class TestIndicators(unittest.TestCase):
    def test_macd_identity(self):
        c = walk()["close"]
        line, sig, hist = macd(c, 12, 26, 9)
        self.assertTrue(np.allclose(line, ema(c, 12) - ema(c, 26)))
        self.assertTrue(np.allclose(hist, line - sig))

    def test_rsi_bounds_and_extremes(self):
        r = rsi(walk()["close"], 14).dropna()
        self.assertTrue(((r >= 0) & (r <= 100)).all())
        up = pd.Series(np.arange(1, 80, dtype=float))
        self.assertAlmostEqual(float(rsi(up, 14).iloc[-1]), 100.0, places=6)
        self.assertAlmostEqual(float(rsi(up[::-1].reset_index(drop=True), 14).iloc[-1]), 0.0, places=6)

    def test_supertrend_side_of_price(self):
        df = walk()
        line, d = supertrend(df, 10, 3.0)
        ok = line.notna()
        up = ok & (d == 1)
        dn = ok & (d == -1)
        self.assertTrue((line[up] <= df["close"][up] + 1e-9).all())    # uptrend: garis di bawah close
        self.assertTrue((line[dn] >= df["close"][dn] - 1e-9).all())    # downtrend: garis di atas close
        self.assertGreater((d.diff().abs() > 0).sum(), 0)

    def test_supertrend_flips_on_reversal(self):
        up = np.linspace(100, 140, 60)
        dn = np.linspace(140, 90, 60)
        c = np.concatenate([up, dn])
        o = np.concatenate([[c[0]], c[:-1]])
        df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.3, "low": np.minimum(o, c) - 0.3, "close": c,
                           "volume": 1.0}, index=pd.date_range("2026-01-01", periods=len(c), freq="1h", tz="UTC"))
        _, d = supertrend(df, 10, 3.0)
        self.assertEqual(int(d.iloc[55]), 1)
        self.assertEqual(int(d.iloc[-1]), -1)

    def test_utcs_signals_only_on_flip(self):
        df = walk(seed=9)
        trail, d, buy, sell = utcs(df, 10, 1.0)
        for i in np.flatnonzero(buy.to_numpy()):
            self.assertEqual((int(d.iloc[i - 1]), int(d.iloc[i])), (-1, 1))
        for i in np.flatnonzero(sell.to_numpy()):
            self.assertEqual((int(d.iloc[i - 1]), int(d.iloc[i])), (1, -1))
        self.assertGreater(int(buy.sum() + sell.sum()), 0)

    def test_no_lookahead(self):
        """Nilai indikator di candle k tidak boleh berubah saat data setelah k ditambahkan."""
        df = walk(500)
        k = 350
        a = add_indicators(df.iloc[:k + 1])
        b = add_indicators(df)
        for col in ("ema12", "ema200", "macd", "macd_signal", "rsi", "obv", "st", "st_dir", "utcs", "utcs_dir", "vol_sma"):
            x, y = a[col].iloc[-1], b[col].iloc[k]
            self.assertTrue((np.isnan(x) and np.isnan(y)) or abs(float(x) - float(y)) < 1e-9, col)

    def test_ema_warmup_blank(self):
        x = add_indicators(walk(300))
        self.assertTrue(x["ema200"].iloc[:200].isna().all())
        self.assertTrue(x["ema200"].iloc[200:].notna().all())
        self.assertTrue(x["ema12"].iloc[12:].notna().all())


def daily_frame(start, days, base=100.0):
    idx = pd.date_range(start, periods=days, freq="1D", tz="UTC")
    k = np.arange(days, dtype=float)
    o = base + k
    return pd.DataFrame({"open": o, "high": o + 5 + (k % 7), "low": o - 5 - (k % 5), "close": o + 1, "volume": 10.0}, index=idx)


class TestKeyLevels(unittest.TestCase):
    def setUp(self):
        self.now = pd.Timestamp("2026-11-18 10:20", tz="UTC")   # Rabu
        d = daily_frame("2025-11-18", 365)
        d = d[d.index < self.now.normalize()]
        h = pd.DataFrame({"open": 500.0, "high": 505.0, "low": 495.0, "close": 501.0, "volume": 1.0},
                         index=pd.date_range("2026-11-17 00:00", "2026-11-18 09:00", freq="1h", tz="UTC"))
        h4 = pd.DataFrame({"open": 480.0, "high": 520.0, "low": 470.0, "close": 490.0, "volume": 1.0},
                          index=pd.date_range("2026-11-17 00:00", "2026-11-18 04:00", freq="4h", tz="UTC"))
        self.f = {"1d": d, "1h": h, "4h": h4}
        self.d = d

    def by(self, ks):
        out = {}
        for k in ks:                      # level kembar digabung ("DO & 4H-O") -> petakan tiap kode
            for code in k.code.split(" & "):
                out[code] = k.price
        return out

    def test_previous_day_week_month(self):
        ks = self.by(compute_key_levels(self.f, self.now, None, {}))
        pd_ = self.d.iloc[-1]
        self.assertAlmostEqual(ks["PDH"], pd_["high"])
        self.assertAlmostEqual(ks["PDL"], pd_["low"])
        self.assertAlmostEqual(ks["PDM"], (pd_["high"] + pd_["low"]) / 2)
        wk = self.now.normalize() - pd.Timedelta(days=self.now.weekday())
        pw = self.d[(self.d.index >= wk - pd.Timedelta(days=7)) & (self.d.index < wk)]
        self.assertAlmostEqual(ks["PWH"], pw["high"].max())
        self.assertAlmostEqual(ks["PWL"], pw["low"].min())
        pm = self.d[(self.d.index >= "2026-10-01") & (self.d.index < "2026-11-01")]
        self.assertAlmostEqual(ks["PMH"], pm["high"].max())
        self.assertAlmostEqual(ks["PML"], pm["low"].min())

    def test_opens(self):
        ks = self.by(compute_key_levels(self.f, self.now, None, {}))
        self.assertAlmostEqual(ks["DO"], 500.0)                                   # candle 1H pertama hari ini
        wk = self.now.normalize() - pd.Timedelta(days=self.now.weekday())         # Senin: ada di 1d
        self.assertAlmostEqual(ks["WO"], float(self.d.loc[wk, "open"]))
        self.assertAlmostEqual(ks["MO"], float(self.d.loc["2026-11-01", "open"]))
        self.assertAlmostEqual(ks["P4H-H"], 520.0)

    def test_no_lookahead_future_candle_ignored(self):
        base = self.by(compute_key_levels(self.f, self.now, None, {}))
        f2 = dict(self.f)
        fut = self.f["1h"].copy()
        fut.loc[pd.Timestamp("2026-11-18 10:00", tz="UTC")] = [9999.0, 9999.0, 1.0, 5000.0, 1.0]   # candle yang belum close pada `now`
        f2["1h"] = fut
        # kontrak fetcher: hanya candle close yang masuk frame; di sini kita pastikan level periode LALU tidak berubah
        again = self.by(compute_key_levels(f2, self.now, None, {}))
        for code in ("PDH", "PDL", "PWH", "PWL", "PMH", "PML"):
            self.assertAlmostEqual(base[code], again[code])

    def test_incomplete_period_skipped(self):
        short = {"1d": self.d.iloc[-10:], "1h": self.f["1h"], "4h": self.f["4h"]}   # data hanya 10 hari -> tak ada bulan/kuartal lalu
        ks = self.by(compute_key_levels(short, self.now, None, {}))
        self.assertNotIn("PMH", ks)
        self.assertNotIn("PQH", ks)
        self.assertNotIn("CYH", ks)

    def test_monday_and_toggles(self):
        mr = MondayRange(high=111.0, low=99.0, date=pd.Timestamp("2026-11-16", tz="UTC"))
        ks = self.by(compute_key_levels(self.f, self.now, mr, {}))
        self.assertAlmostEqual(ks["MDAY-H"], 111.0)
        self.assertAlmostEqual(ks["MDAY-M"], 105.0)
        off = self.by(compute_key_levels(self.f, self.now, mr, {"monday": False, "mid": False, "yearly": False}))
        self.assertNotIn("MDAY-H", off)
        self.assertFalse([c for c in off if c.endswith("M")])
        self.assertNotIn("CYH", off)

    def test_overlap_merged(self):
        d = self.f["1d"].copy()
        pdr = d.iloc[-1]
        mr = MondayRange(high=float(pdr["high"]), low=1.0, date=pd.Timestamp("2026-11-16", tz="UTC"))
        ks = compute_key_levels(self.f, self.now, mr, {})
        merged = [k for k in ks if "PDH" in k.code and "MDAY-H" in k.code]
        self.assertEqual(len(merged), 1)


class TestConfigHash(unittest.TestCase):
    def test_visual_params_do_not_change_hash(self):
        import copy
        from src.utils import config_hash, strategy_params, strategy_symbols_cfg
        cfg = load_config("config")
        h0 = config_hash(strategy_symbols_cfg(cfg.symbols_cfg), strategy_params(cfg.params), cfg.risk)
        p2 = copy.deepcopy(cfg.params)
        p2["chart_indicators"]["rsi"]["period"] = 7
        p2["chart"]["show"]["obv"] = False
        sc2 = copy.deepcopy(cfg.symbols_cfg)
        sc2["symbols"] = ["BTC/USDT"]                         # universe dinamis tidak boleh mengubah hash
        sc2["universe"]["top_n"] = 10
        self.assertEqual(h0, config_hash(strategy_symbols_cfg(sc2), strategy_params(p2), cfg.risk))
        p2["scoring"]["min_score"] = 99                      # parameter strategi -> hash harus berubah
        self.assertNotEqual(h0, config_hash(strategy_symbols_cfg(cfg.symbols_cfg), strategy_params(p2), cfg.risk))


class TestChartExport(unittest.TestCase):
    def test_export_and_png(self):
        from src.analysis.pipeline import analyze_symbol
        from src.report.chart_data import export_chart_data
        from src.report.chart_generator import generate_chart
        from src.signal.signal_engine import evaluate_symbol
        cfg = load_config("config")
        now = pd.Timestamp("2026-11-22 08:20", tz="UTC")
        candles = {tf: int(cfg.symbols_cfg["candles"][tf]) for tf in cfg.all_timeframes}
        data = DemoSource().fetch_symbol("BTC/USDT", candles, now=now)
        an = analyze_symbol("BTC/USDT", data, cfg, now)
        sig = evaluate_symbol(an, cfg, an.bias, now)
        with tempfile.TemporaryDirectory() as td:
            n = export_chart_data({"BTC/USDT": an}, [sig], cfg, Path(td))
            self.assertEqual(n, 4)
            idx = json.loads((Path(td) / "chartdata" / "index.json").read_text())
            self.assertEqual(idx["symbols"]["BTC/USDT"]["tfs"], ["15m", "1h", "4h", "1d"])
            raw = (Path(td) / "chartdata" / "BTC_USDT_1h.json").read_text()
            self.assertNotIn("NaN", raw)                                   # JSON valid untuk browser
            d = json.loads(raw)
            n_c = len(d["t"])
            for k in ("o", "h", "l", "c", "v"):
                self.assertEqual(len(d[k]), n_c)
            for k, v in d["ind"].items():
                if k not in ("utcs_buy", "utcs_sell"):
                    self.assertEqual(len(v), n_c, k)
            self.assertTrue(d["levels"])
            self.assertIsNotNone(d["ind"]["ema200"][-1])
            png = Path(td) / "c.png"
            self.assertTrue(generate_chart(an, sig, cfg, png))
            self.assertGreater(png.stat().st_size, 20000)


if __name__ == "__main__":
    unittest.main()
