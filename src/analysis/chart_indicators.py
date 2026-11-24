"""Kumpulan indikator untuk grafik: EMA 12/26/100/200, MACD, RSI, OBV, Volume, Supertrend, UTCS.
Dihitung pada SELURUH frame (agar EMA200 dkk sudah konvergen) baru kemudian dipotong untuk tampilan.
Semua parameter ada di parameters.yaml -> chart_indicators. Murni visual: TIDAK mengubah skor/signal."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from ..data.indicators import ema, macd, obv, rsi, sma, supertrend, utcs

DEFAULTS: Dict[str, Any] = {
    "ema": {"fast": 12, "slow": 26, "mid": 100, "long": 200},
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "rsi": {"period": 14, "overbought": 70, "oversold": 30},
    "obv": {"signal_ema": 21},
    "volume": {"sma": 20},
    "supertrend": {"period": 10, "multiplier": 3.0},
    "utcs": {"atr_period": 10, "key": 1.0},
}


def ind_cfg(params: Dict[str, Any] | None) -> Dict[str, Any]:
    """Gabungkan default dengan parameters.yaml -> chart_indicators (per-section)."""
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for k, v in ((params or {}).get("chart_indicators") or {}).items():
        if k in out and isinstance(v, dict):
            out[k].update(v)
    return out


def _warm(s: pd.Series, n: int) -> pd.Series:
    """EMA belum konvergen pada n candle pertama -> kosongkan (jujur, tidak menampilkan angka palsu)."""
    s = s.copy()
    s.iloc[: min(n, len(s))] = np.nan
    return s


def add_indicators(df: pd.DataFrame, params: Dict[str, Any] | None = None) -> pd.DataFrame:
    c = ind_cfg(params)
    e, m, r, o, v, st, u = c["ema"], c["macd"], c["rsi"], c["obv"], c["volume"], c["supertrend"], c["utcs"]
    out = pd.DataFrame(index=df.index)
    for key, name in (("fast", "ema12"), ("slow", "ema26"), ("mid", "ema100"), ("long", "ema200")):
        n = int(e[key])
        out[name] = _warm(ema(df["close"], n), n)
    ml, ms, mh = macd(df["close"], int(m["fast"]), int(m["slow"]), int(m["signal"]))
    warm = int(m["slow"]) + int(m["signal"])
    out["macd"], out["macd_signal"], out["macd_hist"] = _warm(ml, warm), _warm(ms, warm), _warm(mh, warm)
    out["rsi"] = rsi(df["close"], int(r["period"]))
    ob = obv(df)
    out["obv"] = ob
    out["obv_ema"] = _warm(ema(ob, int(o["signal_ema"])), int(o["signal_ema"]))
    out["vol_sma"] = sma(df["volume"], int(v["sma"]))
    out["st"], out["st_dir"] = supertrend(df, int(st["period"]), float(st["multiplier"]))
    out["utcs"], out["utcs_dir"], out["utcs_buy"], out["utcs_sell"] = utcs(df, int(u["atr_period"]), float(u["key"]))
    return out
