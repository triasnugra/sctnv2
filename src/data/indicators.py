"""Indikator dasar & primitif pattern (pivot, ATR, OBV, volume).
Detektor spesifik (deviation, fib, dll) ada di src/analysis/."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

_TF_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def tf_to_timedelta(tf: str) -> pd.Timedelta:
    unit, num = tf[-1], int(tf[:-1])
    if unit not in _TF_SECONDS:
        raise ValueError(f"Timeframe tidak didukung: {tf}")
    return pd.Timedelta(seconds=num * _TF_SECONDS[unit])


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def last_atr(df: pd.DataFrame, period: int = 14) -> float:
    v = atr(df, period).iloc[-1]
    if v is None or np.isnan(v):
        v = float((df["high"] - df["low"]).tail(period).mean())
    return float(v)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(2, n // 2)).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def volume_ratio(df: pd.DataFrame, recent: int = 3, base: int = 50) -> float:
    v = df["volume"]
    if len(v) < recent + 10:
        return float("nan")
    base = min(base, len(v) - recent)
    b = v.iloc[-(recent + base):-recent].mean()
    if b <= 0 or np.isnan(b):
        return float("nan")
    return float(v.iloc[-recent:].mean() / b)


def vol_sma_prior(v: np.ndarray, n: int = 20) -> np.ndarray:
    """SMA volume dari n candle SEBELUM tiap indeks (eksklusif)."""
    return pd.Series(v).rolling(n, min_periods=5).mean().shift(1).to_numpy()


@dataclass
class Pivot:
    idx: int
    price: float
    kind: str  # 'H' | 'L'


def find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> List[Pivot]:
    """Swing high/low terkonfirmasi (butuh `right` candle setelahnya).
    High: > semua `left` candle sebelumnya dan >= semua `right` candle sesudahnya."""
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    n = len(df)
    out: List[Pivot] = []
    for i in range(left, n - right):
        if h[i] > h[i - left:i].max() and h[i] >= h[i + 1:i + right + 1].max():
            out.append(Pivot(i, float(h[i]), "H"))
        if l[i] < l[i - left:i].min() and l[i] <= l[i + 1:i + right + 1].min():
            out.append(Pivot(i, float(l[i]), "L"))
    out.sort(key=lambda p: p.idx)
    return out


def merge_alternating(pivots: List[Pivot]) -> List[Pivot]:
    """Pastikan pivot selang-seling H/L; jika dua sejenis berurutan ambil yang lebih ekstrem."""
    out: List[Pivot] = []
    for p in sorted(pivots, key=lambda x: x.idx):
        if out and out[-1].kind == p.kind:
            if (p.kind == "H" and p.price > out[-1].price) or (p.kind == "L" and p.price < out[-1].price):
                out[-1] = p
        else:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Indikator untuk GRAFIK (MACD, RSI, Supertrend, UTCS). Murni visual: tidak ikut skor signal.
# ---------------------------------------------------------------------------
def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD klasik: (garis, sinyal, histogram)."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI Wilder (RMA). Nilai 0..100; NaN sampai data cukup."""
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    ad = dn.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = au / ad.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(~((ad == 0) & (au > 0)), 100.0)   # tidak ada penurunan sama sekali -> 100
    out = out.where(~((au == 0) & (ad > 0)), 0.0)
    return out


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """Supertrend (ATR Wilder). Default 10/3 sesuai catatan @eliz883.
    Return (garis, arah): arah +1 = uptrend (garis di bawah harga), -1 = downtrend (garis di atas harga)."""
    n = len(df)
    a = atr(df, period).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2.0).to_numpy()
    c = df["close"].to_numpy()
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    fu = np.full(n, np.nan)
    fl = np.full(n, np.nan)
    start = next((i for i in range(n) if not np.isnan(a[i])), None)
    if start is None:
        return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)
    for i in range(start, n):
        up_b, lo_b = hl2[i] + mult * a[i], hl2[i] - mult * a[i]
        if i == start:
            fu[i], fl[i] = up_b, lo_b
            direction[i] = 1 if c[i] >= hl2[i] else -1
        else:
            fu[i] = up_b if (up_b < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
            fl[i] = lo_b if (lo_b > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
            if direction[i - 1] == -1 and c[i] > fu[i - 1]:
                direction[i] = 1
            elif direction[i - 1] == 1 and c[i] < fl[i - 1]:
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]
        line[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def utcs(df: pd.DataFrame, atr_period: int = 10, key: float = 1.0):
    """UTCS (APROKSIMASI TERBUKA): ATR trailing-stop flip ala 'UT Bot'.
    Sumber indikator UCTS/UTCS asli (CryptoNTez) tertutup, jadi ini BUKAN replika persis — hanya pendekatan
    transparan: BUY saat close menembus trailing stop ke atas, SELL saat menembus ke bawah.
    Return (trail, arah, buy, sell); arah +1/-1; buy/sell = Series boolean."""
    n = len(df)
    c = df["close"].to_numpy()
    a = atr(df, atr_period).to_numpy()
    trail = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    start = next((i for i in range(n) if not np.isnan(a[i])), None)
    if start is not None:
        trail[start] = c[start] - key * a[start]
        direction[start] = 1
        for i in range(start + 1, n):
            nl = key * a[i]
            p = trail[i - 1]
            if c[i] > p and c[i - 1] > p:
                trail[i] = max(p, c[i] - nl)
            elif c[i] < p and c[i - 1] < p:
                trail[i] = min(p, c[i] + nl)
            elif c[i] > p:
                trail[i] = c[i] - nl
            else:
                trail[i] = c[i] + nl
            direction[i] = 1 if c[i] > trail[i] else (-1 if c[i] < trail[i] else direction[i - 1])
            buy[i] = direction[i] == 1 and direction[i - 1] == -1
            sell[i] = direction[i] == -1 and direction[i - 1] == 1
    idx = df.index
    return pd.Series(trail, index=idx), pd.Series(direction, index=idx), pd.Series(buy, index=idx), pd.Series(sell, index=idx)
