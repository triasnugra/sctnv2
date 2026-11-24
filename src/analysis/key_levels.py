"""Key Levels gaya 'Spaceman BTC' (TradingView 'Key Levels SpacemanBTC IDWM').
Level per periode: Open, Previous High / Low / Mid (Daily, Weekly, Monthly, Quarterly, 4H) + Current-Year H/L/O/Mid + Monday H/L/Mid.
Semua dihitung dari candle yang SUDAH close (tanpa lookahead); 'open' periode berjalan diambil dari candle 1H awal periode.
Level yang periodenya tidak tercakup penuh oleh data dilewati (lebih baik tidak tampil daripada salah)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from ..models import KeyLevel, MondayRange

GROUPS = ("daily", "weekly", "monthly", "quarterly", "yearly", "h4", "monday")


def _since(fine: List[pd.DataFrame], start: pd.Timestamp) -> pd.DataFrame:
    """Candle (sudah close) sejak `start` dari frame halus pertama yang punya data (1H dulu, lalu 15m untuk jam yang baru berjalan)."""
    for f in fine:
        if f is not None and len(f):
            t = f[f.index >= start]
            if len(t):
                return t
    return pd.DataFrame()


def _last_close(fine: List[pd.DataFrame]) -> Optional[float]:
    for f in (fine[1], fine[0]) if len(fine) > 1 else fine:   # frame paling halus dulu
        if f is not None and len(f):
            return float(f["close"].iloc[-1])
    return None


def _today_partial(fine: List[pd.DataFrame], today: pd.Timestamp) -> Optional[pd.Series]:
    """Baris 'hari ini' (sebagian) dari candle halus yang sudah close; None bila belum ada."""
    t = _since(fine, today)
    if t.empty:
        return None
    return pd.Series({"open": float(t["open"].iloc[0]), "high": float(t["high"].max()),
                      "low": float(t["low"].min()), "close": float(t["close"].iloc[-1]),
                      "volume": float(t["volume"].sum())}, name=today)


def _period(d: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, tol_days: int = 1) -> Optional[pd.DataFrame]:
    """Candle harian dalam [start, end). None bila awal periode tidak tercakup data (pemotongan di kiri)."""
    if d.empty or d.index[0] > start + pd.Timedelta(days=tol_days):
        return None
    p = d[(d.index >= start) & (d.index < end)]
    return p if len(p) else None


def _hlm(prefix: str, label: str, group: str, p: pd.DataFrame) -> List[KeyLevel]:
    hi, lo = float(p["high"].max()), float(p["low"].min())
    return [KeyLevel(f"{prefix}H", f"Previous {label} High", hi, group),
            KeyLevel(f"{prefix}L", f"Previous {label} Low", lo, group),
            KeyLevel(f"{prefix}M", f"Previous {label} Mid", (hi + lo) / 2, group)]


def compute_key_levels(frames: Dict[str, pd.DataFrame], now: pd.Timestamp, monday: Optional[MondayRange] = None,
                       cfg: Optional[Dict[str, Any]] = None) -> List[KeyLevel]:
    cfg = cfg or {}
    on = {g: bool(cfg.get(g, True)) for g in GROUPS}
    want_mid = bool(cfg.get("mid", True))
    d1, h1, f4 = frames.get("1d"), frames.get("1h"), frames.get("4h")
    fine = [h1, frames.get("15m")]
    out: List[KeyLevel] = []
    if d1 is not None and len(d1):
        today = now.normalize()
        part = _today_partial(fine, today)
        d = d1[d1.index < today]
        dx = pd.concat([d, part.to_frame().T.astype(float)]) if part is not None else d  # hari ini (sebagian) ikut utk Open/Year
        if on["daily"] and len(d):
            r = d.iloc[-1]
            out += [KeyLevel("PDH", "Previous Day High", float(r["high"]), "daily"),
                    KeyLevel("PDL", "Previous Day Low", float(r["low"]), "daily"),
                    KeyLevel("PDM", "Previous Day Mid", float((r["high"] + r["low"]) / 2), "daily")]
        if on["daily"]:
            do = float(part["open"]) if part is not None else _last_close(fine)   # periode baru, belum ada candle close -> open = close terakhir
            if do is not None:
                out.append(KeyLevel("DO", "Daily Open", do, "daily"))
        # weekly (Senin 00:00 UTC)
        wk = today - pd.Timedelta(days=int(today.weekday()))
        if on["weekly"]:
            p = _period(d, wk - pd.Timedelta(days=7), wk)
            if p is not None and len(p) >= 5:
                out += _hlm("PW", "Week", "weekly", p)
            cur = dx[dx.index >= wk]
            wo = float(cur["open"].iloc[0]) if len(cur) else _last_close(fine)
            if wo is not None:
                out.append(KeyLevel("WO", "Weekly Open", wo, "weekly"))
        # monthly
        ms = today.replace(day=1)
        pms = (ms - pd.Timedelta(days=1)).replace(day=1)
        if on["monthly"]:
            p = _period(d, pms, ms)
            if p is not None and len(p) >= 20:
                out += _hlm("PM", "Month", "monthly", p)
            cur = dx[dx.index >= ms]
            mo = float(cur["open"].iloc[0]) if len(cur) else _last_close(fine)
            if mo is not None:
                out.append(KeyLevel("MO", "Monthly Open", mo, "monthly"))
        # quarterly
        if on["quarterly"]:
            qs = ms.replace(month=((ms.month - 1) // 3) * 3 + 1)
            pqs = (qs - pd.Timedelta(days=1)).replace(day=1)
            pqs = pqs.replace(month=((pqs.month - 1) // 3) * 3 + 1)
            p = _period(d, pqs, qs)
            if p is not None and len(p) >= 60:
                out += _hlm("PQ", "Quarter", "quarterly", p)
            cur = dx[dx.index >= qs]
            qo = float(cur["open"].iloc[0]) if len(cur) else _last_close(fine)
            if qo is not None:
                out.append(KeyLevel("QO", "Quarterly Open", qo, "quarterly"))
        # yearly (tahun berjalan)
        if on["yearly"]:
            ys = today.replace(month=1, day=1)
            cur = _period(dx, ys, today + pd.Timedelta(days=1))
            if cur is not None and len(cur) >= 20:
                hi, lo = float(cur["high"].max()), float(cur["low"].min())
                out += [KeyLevel("CYH", "Current Year High", hi, "yearly"), KeyLevel("CYL", "Current Year Low", lo, "yearly"),
                        KeyLevel("CYM", "Current Year Mid", (hi + lo) / 2, "yearly"),
                        KeyLevel("YO", "Yearly Open", float(cur["open"].iloc[0]), "yearly")]
    # 4H
    if on["h4"] and f4 is not None and len(f4):
        closed = f4[f4.index + pd.Timedelta(hours=4) <= now]
        if len(closed):
            r = closed.iloc[-1]
            out += [KeyLevel("P4H-H", "Previous 4H High", float(r["high"]), "h4"),
                    KeyLevel("P4H-L", "Previous 4H Low", float(r["low"]), "h4"),
                    KeyLevel("P4H-M", "Previous 4H Mid", float((r["high"] + r["low"]) / 2), "h4")]
        cur = _since(fine, now.floor("4h"))
        ho = float(cur["open"].iloc[0]) if len(cur) else _last_close(fine)
        if ho is not None:
            out.append(KeyLevel("4H-O", "4H Open", ho, "h4"))
    # Monday range
    if on["monday"] and monday is not None:
        tag = " (minggu lalu)" if monday.is_previous else ""
        out += [KeyLevel("MDAY-H", "Monday High" + tag, monday.high, "monday"),
                KeyLevel("MDAY-L", "Monday Low" + tag, monday.low, "monday"),
                KeyLevel("MDAY-M", "Monday Mid" + tag, monday.mid, "monday")]
    if not want_mid:
        out = [k for k in out if not k.code.endswith("M")]   # semua kode 'mid' berakhiran M (PDM, PWM, P4H-M, MDAY-M, ...)
    return _merge_overlaps(out)


def _merge_overlaps(levels: List[KeyLevel]) -> List[KeyLevel]:
    """Level kembar pada harga yang sama digabung labelnya (seperti 'weekly open & daily open' di Spaceman)."""
    out: List[KeyLevel] = []
    for k in levels:
        for o in out:
            if abs(o.price - k.price) <= max(abs(o.price), 1e-12) * 1e-9:
                o.code += " & " + k.code
                o.name += " & " + k.name
                break
        else:
            out.append(KeyLevel(k.code, k.name, k.price, k.group))
    return out
