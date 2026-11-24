"""Ekspor data chart interaktif (JSON) untuk dashboard: candle + semua indikator + key level + plan.
Satu file per simbol x timeframe: output/latest/chartdata/<SIMBOL>_<tf>.json  + index.json.
Indikator dihitung di Python (satu sumber kebenaran, sama dengan PNG); JS hanya menggambar."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..analysis.chart_indicators import add_indicators, ind_cfg
from ..analysis.key_levels import compute_key_levels
from ..config_loader import Config
from ..models import Signal, SymbolAnalysis
from ..utils import safe_name

log = logging.getLogger("engine.chartdata")

DEFAULT_EXPORT = {"timeframes": ["15m", "1h", "4h", "1d"], "candles": {"15m": 400, "1h": 400, "4h": 300, "1d": 300},
                  "default_visible": 120}


def _num(x) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return float(f"{f:.8g}")


def _arr(s: pd.Series) -> List[Optional[float]]:
    return [_num(v) for v in s.to_numpy()]


def export_cfg(cfg: Config) -> dict:
    out = dict(DEFAULT_EXPORT)
    out.update((cfg.params.get("chart_indicators") or {}).get("export") or {})
    return out


def build_chart_payload(an: SymbolAnalysis, sig: Optional[Signal], cfg: Config, tf: str, n_candles: int) -> Optional[dict]:
    full = an.frames.get(tf)
    if full is None or len(full) < 30:
        return None
    ind = add_indicators(full, cfg.params)
    df = full.iloc[-n_candles:]
    ind = ind.iloc[-len(df):]
    icfg = ind_cfg(cfg.params)
    klcfg = (cfg.params.get("chart_indicators") or {}).get("key_levels") or {}
    levels = [{"code": k.code, "name": k.name, "price": _num(k.price), "group": k.group}
              for k in compute_key_levels(an.frames, an.asof, an.monday, klcfg)]
    ranges = {rtf: {"low": _num(rb.low), "high": _num(rb.high), "mid": _num(rb.mid),
                    "demand_top": _num(rb.demand_top), "supply_bottom": _num(rb.supply_bottom),
                    "start": int(pd.Timestamp(rb.start_time).timestamp())} for rtf, rb in an.ranges.items()}
    fibs = [{"tf": f.tf, "level": _num(f.level_price), "lo": _num(f.zone_lo), "hi": _num(f.zone_hi),
             "state": f.state, "direction": f.direction} for f in an.fibs if f.tf == tf and f.state != "invalidated"]
    plan = None
    if sig is not None and sig.plan is not None and sig.action in ("LONG", "SHORT"):
        p = sig.plan
        plan = {"direction": p.direction, "entry": _num(p.entry), "stop": _num(p.stop), "tp1": _num(p.tp1), "tp2": _num(p.tp2),
                "zone": [_num(p.entry_zone[0]), _num(p.entry_zone[1])] if p.entry_zone else None, "status": sig.status}
    ub = np.flatnonzero(ind["utcs_buy"].to_numpy()).tolist()
    us = np.flatnonzero(ind["utcs_sell"].to_numpy()).tolist()
    ex = export_cfg(cfg)
    return {
        "symbol": an.symbol, "tf": tf, "asof": an.asof.isoformat(), "price": _num(an.price),
        "action": sig.action if sig else "NO TRADE",
        "params": {"ema": icfg["ema"], "macd": icfg["macd"], "rsi": icfg["rsi"], "obv": icfg["obv"],
                   "supertrend": icfg["supertrend"], "utcs": icfg["utcs"], "volume": icfg["volume"]},
        "default_visible": int(ex.get("default_visible", 120)),
        "t": [int(ts.timestamp()) for ts in df.index],
        "o": _arr(df["open"]), "h": _arr(df["high"]), "l": _arr(df["low"]), "c": _arr(df["close"]), "v": _arr(df["volume"]),
        "ind": {k: _arr(ind[k]) for k in ("ema12", "ema26", "ema100", "ema200", "macd", "macd_signal", "macd_hist",
                                           "rsi", "obv", "obv_ema", "vol_sma", "st", "utcs")}
               | {"st_dir": [int(v) for v in ind["st_dir"].to_numpy()],
                  "utcs_dir": [int(v) for v in ind["utcs_dir"].to_numpy()],
                  "utcs_buy": ub, "utcs_sell": us},
        "levels": levels, "ranges": ranges, "fibs": fibs, "plan": plan,
    }


def export_chart_data(analyses: Dict[str, SymbolAnalysis], signals: List[Signal], cfg: Config, latest_dir: Path) -> int:
    """Tulis semua JSON chart; return jumlah file. Kegagalan satu simbol/TF tidak mematikan yang lain."""
    ex = export_cfg(cfg)
    outdir = Path(latest_dir) / "chartdata"
    outdir.mkdir(parents=True, exist_ok=True)
    sigs = {s.symbol: s for s in signals}
    index: Dict[str, dict] = {}
    count = 0
    for sym, an in analyses.items():
        tfs_ok: List[str] = []
        for tf in ex["timeframes"]:
            try:
                payload = build_chart_payload(an, sigs.get(sym), cfg, tf, int((ex.get("candles") or {}).get(tf, 300)))
                if payload is None:
                    continue
                (outdir / f"{safe_name(sym)}_{tf}.json").write_text(
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
                tfs_ok.append(tf)
                count += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("%s %s: ekspor chart data gagal: %s", sym, tf, exc)
        if tfs_ok:
            index[sym] = {"file": safe_name(sym), "tfs": tfs_ok}
    (outdir / "index.json").write_text(json.dumps({"asof": max((a.asof for a in analyses.values()), default=None).isoformat()
                                                    if analyses else None,
                                                    "default_tf": cfg.tfs.get("primary_trigger", "1h"), "symbols": index},
                                                   separators=(",", ":")), encoding="utf-8")
    return count
