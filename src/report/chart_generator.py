"""Chart candlestick (matplotlib, headless) dengan anotasi level, entry zone, stop, target."""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from ..analysis.chart_indicators import add_indicators, ind_cfg  # noqa: E402
from ..analysis.key_levels import compute_key_levels  # noqa: E402
from ..config_loader import Config  # noqa: E402
from ..models import Signal, SymbolAnalysis  # noqa: E402
from ..utils import fmt_price  # noqa: E402

log = logging.getLogger("engine.chart")
PAD = 34

EMA_STYLE = [("ema12", "EMA 12", "#f9a825", 1.0), ("ema26", "EMA 26", "#ef6c00", 1.1),
             ("ema100", "EMA 100", "#1565c0", 1.4), ("ema200", "EMA 200", "#6a1b9a", 1.6)]
KL_COLOR = {"daily": "#00897b", "weekly": "#c2185b", "monthly": "#5d4037", "quarterly": "#455a64",
            "yearly": "#263238", "h4": "#78909c", "monday": "#1e88e5"}


def generate_chart(an: SymbolAnalysis, sig: Signal, cfg: Config, out_path: Path) -> bool:
    ccfg = cfg.params.get("chart", {})
    tf = ccfg.get("timeframe", "1h")
    if ccfg.get("follow_trigger_tf", True) and sig.primary is not None and sig.primary.tf in an.frames:
        tf = sig.primary.tf
    if tf not in an.frames:
        tf = cfg.tfs["primary_trigger"]
    df = an.frames[tf].iloc[-int(ccfg.get("candles", 160)):]
    n = len(df)
    if n < 20:
        return False
    x = np.arange(n)
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    # indikator dihitung pada SELURUH frame (EMA200 konvergen) lalu dipotong sesuai tampilan
    icfg = ind_cfg(cfg.params)
    full = an.frames[tf]
    ind = add_indicators(full, cfg.params).iloc[-n:]
    show = {k: bool((ccfg.get("show") or {}).get(k, True))
            for k in ("ema", "supertrend", "utcs", "volume", "key_levels", "macd", "rsi", "obv")}
    sub = [k for k in ("macd", "rsi", "obv") if show[k]]
    ratios = [5.2] + [1.25] * len(sub)
    fig, axes = plt.subplots(len(sub) + 1, 1, figsize=(14, 7.5 + 1.9 * len(sub)), dpi=int(ccfg.get("dpi", 110)),
                             sharex=True, gridspec_kw={"height_ratios": ratios, "hspace": 0.06})
    axes = np.atleast_1d(axes)
    ax = axes[0]
    up = c >= o
    col = np.where(up, "#26a69a", "#ef5350")
    if show["volume"]:  # volume sebagai overlay di dasar panel harga (gaya TradingView)
        axv = ax.twinx()
        axv.bar(x, v, width=0.7, color=col, alpha=0.30, zorder=0)
        axv.plot(x, ind["vol_sma"].to_numpy(), color="#757575", lw=0.8, zorder=0)
        axv.set_ylim(0, max(float(np.nanmax(v)), 1e-9) * 5.0)
        axv.set_yticks([])
        ax.set_zorder(axv.get_zorder() + 1)
        ax.patch.set_visible(False)
    ax.vlines(x, l, h, colors=col, linewidth=0.8, zorder=3)
    ax.bar(x, np.maximum(np.abs(c - o), c.mean() * 1e-5), bottom=np.minimum(o, c), width=0.6, color=col, zorder=4)

    ymin, ymax = float(l.min()), float(h.max())
    plan = sig.plan
    if plan:
        ymin, ymax = min(ymin, plan.stop), max(ymax, plan.tp1)
        ymin, ymax = min(ymin, plan.tp1), max(ymax, plan.stop)
    span = ymax - ymin
    lo_v, hi_v = ymin - 0.15 * span, ymax + 0.15 * span

    def to_x(ts):
        return int(min(max(df.index.searchsorted(ts), 0), n - 1))

    labels = []

    def hline(price, label, color, ls="--", lw=1.0):
        if not (lo_v <= price <= hi_v):
            return
        ax.hlines(price, 0, n + 1, colors=color, linestyles=ls, linewidth=lw, zorder=2)
        labels.append([price, f"{label} {fmt_price(price)}", color])

    # ---- overlay indikator pada panel harga ----
    handles = []
    if show["ema"]:
        for key, label, color, lw in EMA_STYLE:
            arr = ind[key].to_numpy()
            if np.isfinite(arr).any():
                handles += ax.plot(x, arr, color=color, lw=lw, label=label, zorder=5)
    if show["supertrend"]:
        st, sd = ind["st"].to_numpy(), ind["st_dir"].to_numpy()
        for d_, color, name in ((1, "#2e7d32", "Supertrend ↑"), (-1, "#c62828", "Supertrend ↓")):
            seg = np.where(sd == d_, st, np.nan)
            if np.isfinite(seg).any():
                handles += ax.plot(x, seg, color=color, lw=1.7, label=name, zorder=5)
    if show["utcs"]:
        ub, us = ind["utcs_buy"].to_numpy(), ind["utcs_sell"].to_numpy()
        off = (hi_v - lo_v) * 0.02
        if ub.any():
            handles.append(ax.scatter(x[ub], l[ub] - off, marker="^", s=46, color="#00c853", edgecolor="black", linewidth=0.4,
                                      zorder=7, label="UTCS buy"))
        if us.any():
            handles.append(ax.scatter(x[us], h[us] + off, marker="v", s=46, color="#ff1744", edgecolor="black", linewidth=0.4,
                                      zorder=7, label="UTCS sell"))
    if show["key_levels"]:
        klcfg = (ccfg.get("key_levels") or cfg.params.get("chart_indicators", {}).get("key_levels") or {})
        for kl in compute_key_levels(an.frames, an.asof, an.monday, klcfg):
            hline(kl.price, kl.code, KL_COLOR.get(kl.group, "#607d8b"), ":" if kl.code.endswith("M") else "--", 0.9)

    # range box (TF chart) & range TF lain
    for rtf, rb in an.ranges.items():
        if rtf == tf:
            x0 = to_x(rb.start_time)
            ax.add_patch(Rectangle((x0, rb.low), n - x0, rb.height, color="#9e9e9e", alpha=0.10, zorder=1))
            ax.add_patch(Rectangle((x0, rb.low), n - x0, rb.demand_top - rb.low, color="#26a69a", alpha=0.12, zorder=1))
            ax.add_patch(Rectangle((x0, rb.supply_bottom), n - x0, rb.high - rb.supply_bottom, color="#ef5350", alpha=0.12, zorder=1))
            hline(rb.high, f"Range H {rtf}", "#616161", "-", 1.2)
            hline(rb.low, f"Range L {rtf}", "#616161", "-", 1.2)
            hline(rb.mid, "Mid", "#9e9e9e", ":", 0.8)
        else:
            hline(rb.high, f"Range H {rtf}", "#7e57c2", ":", 1.0)
            hline(rb.low, f"Range L {rtf}", "#7e57c2", ":", 1.0)
    if an.monday and not show["key_levels"]:
        hline(an.monday.high, "Monday H", "#1e88e5", "--")
        hline(an.monday.low, "Monday L", "#1e88e5", "--")
    for fs in an.fibs:
        if fs.tf == tf and fs.state != "invalidated":
            ax.add_patch(Rectangle((to_x(fs.b_time), fs.zone_lo), n - to_x(fs.b_time), fs.zone_hi - fs.zone_lo,
                                   color="#ffb300", alpha=0.18, zorder=1))
            ax.plot([to_x(fs.a_time), to_x(fs.b_time)], [fs.a_price, fs.b_price], color="#ffb300", lw=1.2, ls="-.", zorder=2)
            hline(fs.level_price, "Fib 0.75", "#ff8f00", "--")
    near_fvgs = sorted([z for z in an.fvgs if z.tf == tf], key=lambda z: abs((z.low + z.high) / 2 - an.price))[:4]
    for z in near_fvgs:
        if True:
            x0 = to_x(z.time)
            ax.add_patch(Rectangle((x0, z.low), n - x0, z.high - z.low,
                                   color="#26a69a" if z.direction == "LONG" else "#ef5350", alpha=0.20, zorder=1))
    # trigger marker
    if sig.primary is not None and sig.primary.time is not None and sig.primary.tf == tf:
        xi = to_x(sig.primary.time)
        ax.annotate(sig.primary.kind.replace("_", " "), xy=(xi, c[xi]), xytext=(xi - 12, c[xi] + (0.06 if sig.primary.direction == "SHORT" else -0.06) * span),
                    arrowprops=dict(arrowstyle="->", color="black"), fontsize=8, zorder=6)
    # plan
    if plan:
        if plan.entry_zone:
            ax.axhspan(plan.entry_zone[0], plan.entry_zone[1], color="#1976d2", alpha=0.18, zorder=1)
        hline(plan.entry, "ENTRY", "#1976d2", "-", 1.6)
        hline(plan.stop, f"STOP ({plan.stop_pct:.2f}%)", "#d32f2f", "-", 1.6)
        hline(plan.tp1, f"TP1 ({plan.rr1:.1f}R)", "#2e7d32", "-", 1.4)
        hline(plan.tp2, f"TP2 ({plan.rr2:.1f}R)", "#66bb6a", "--", 1.2)
    # de-overlap label di margin kanan
    labels.sort(key=lambda t: t[0])
    gap = (hi_v - lo_v) * 0.028
    ys = [t[0] for t in labels]
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < gap:
            ys[i] = ys[i - 1] + gap
    for (price, text, color), y in zip(labels, ys):
        ax.text(n + 1.5, y, text, fontsize=7.5, va="center", color=color)
        if abs(y - price) > 1e-12:
            ax.plot([n + 1, n + 1.4], [price, y], color=color, lw=0.6)
    ax.set_xlim(-1, n + PAD)
    ax.set_ylim(lo_v, hi_v)
    ax.grid(alpha=0.2)
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=7, ncol=6, framealpha=0.85, borderpad=0.4)
    ax.yaxis.tick_left()

    def last_tag(a, val, color, fmt="{:.2f}"):
        if val is not None and np.isfinite(val):
            a.text(1.005, val, fmt.format(val), transform=a.get_yaxis_transform(), fontsize=7, color=color, va="center")

    for name, a in zip(sub, axes[1:]):
        a.grid(alpha=0.2)
        if name == "macd":
            m_, s_, hh = ind["macd"].to_numpy(), ind["macd_signal"].to_numpy(), ind["macd_hist"].to_numpy()
            prev = np.concatenate([[np.nan], hh[:-1]])
            hc = np.where(hh >= 0, np.where(hh >= prev, "#26a69a", "#b2dfdb"), np.where(hh <= prev, "#ef5350", "#ffcdd2"))
            a.bar(x, np.nan_to_num(hh), width=0.7, color=hc, zorder=2)
            a.plot(x, m_, color="#1e88e5", lw=1.1, label="MACD", zorder=3)
            a.plot(x, s_, color="#fb8c00", lw=1.1, label="Signal", zorder=3)
            a.axhline(0, color="#9e9e9e", lw=0.7)
            mc = icfg["macd"]
            a.set_ylabel(f"MACD {mc['fast']},{mc['slow']},{mc['signal']}", fontsize=8)
            last_tag(a, m_[-1], "#1e88e5", "{:.4g}")
        elif name == "rsi":
            r_ = ind["rsi"].to_numpy()
            rc = icfg["rsi"]
            a.plot(x, r_, color="#7e57c2", lw=1.2, zorder=3)
            ob_, os_ = float(rc["overbought"]), float(rc["oversold"])
            a.axhline(ob_, color="#ef5350", lw=0.8, ls="--")
            a.axhline(os_, color="#26a69a", lw=0.8, ls="--")
            a.axhline(50, color="#9e9e9e", lw=0.6, ls=":")
            a.fill_between(x, ob_, 100, color="#ef5350", alpha=0.06)
            a.fill_between(x, 0, os_, color="#26a69a", alpha=0.06)
            a.set_ylim(0, 100)
            a.set_yticks([os_, 50, ob_])
            a.set_ylabel(f"RSI {rc['period']}", fontsize=8)
            last_tag(a, r_[-1], "#7e57c2", "{:.1f}")
        else:  # obv
            ob = ind["obv"].to_numpy()
            oe = ind["obv_ema"].to_numpy()
            a.plot(x, ob, color="#1565c0", lw=1.2, zorder=3)
            a.plot(x, oe, color="#fb8c00", lw=1.0, ls="--", zorder=3)
            a.set_ylabel(f"OBV (EMA {icfg['obv']['signal_ema']})", fontsize=8)
            last_tag(a, ob[-1], "#1565c0", "{:.3g}")
        a.tick_params(axis="y", labelsize=7)
    bottom = axes[-1]
    step = max(1, n // 10)
    bottom.set_xticks(x[::step])
    bottom.set_xticklabels([df.index[i].strftime("%m-%d %H:%M") for i in x[::step]], rotation=0, fontsize=8)
    for a in axes[:-1]:
        a.tick_params(axis="x", labelbottom=False)
    title = f"{an.symbol} {tf} — {sig.action}" + (f" ({sig.status})" if sig.action != "NO TRADE" else "")
    ax.set_title(f"{title} | skor {sig.score:g}/{sig.max_score:g} (min {sig.min_score:g}) | bias HTF {sig.bias}", fontsize=11)
    fig.text(0.01, 0.005, f"asof {an.asof.strftime('%Y-%m-%d %H:%M')} UTC — alat analisis, bukan nasihat finansial; parameter = hipotesis.",
             fontsize=7, color="#757575")
    fig.subplots_adjust(left=0.06, right=0.93, top=0.96, bottom=0.05)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return True
