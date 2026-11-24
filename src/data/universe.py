"""Scanner universe koin otomatis (menggantikan daftar simbol manual).

Mode (config/symbols.yaml -> universe.mode):
  static         : pakai daftar `symbols` di YAML (perilaku lama).
  top_volume     : top-N pasangan spot USDT berdasarkan volume 24 jam (Binance / Bitget / OKX ...).
  top_marketcap  : top-N berdasarkan peringkat market cap (CoinGecko tanpa API key, atau CoinMarketCap bila CMC_API_KEY ada),
                   lalu dipetakan ke pasangan USDT yang benar-benar tersedia di exchange.

Prinsip: gagal ambil universe TIDAK menghentikan engine -> turun ke sumber berikutnya, terakhir ke daftar statis.
Stablecoin, token berleverage (UP/DOWN/BULL/BEAR), dan token wrapped/staked dikeluarkan. Fungsi HTTP/ccxt bisa diinjeksi untuk tes."""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

import requests

log = logging.getLogger("engine.universe")

STABLES = {"USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDD", "USDE", "PYUSD", "USD1", "EUR", "EURI", "AEUR",
           "GUSD", "FRAX", "LUSD", "USDS", "XUSD", "RLUSD", "BFUSD", "USDG", "UST", "USTC", "SUSD", "CRVUSD", "USDX"}
WRAPPED = {"WBTC", "WETH", "STETH", "WSTETH", "WBETH", "BETH", "WBNB", "CBBTC", "CBETH", "RETH", "BNSOL", "JITOSOL", "MSOL",
           "WEETH", "EZETH", "RSETH", "SOLVBTC", "TBTC", "LBTC", "USDTB"}
LEVERAGED_SUFFIX = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")
BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com",
                 "https://api2.binance.com", "https://api3.binance.com"]


class UniverseError(Exception):
    pass


LEVERAGED_STEMS = {"BTC", "ETH", "BNB", "XRP", "LINK", "ADA", "DOT", "EOS", "LTC", "TRX", "BCH", "XTZ", "SOL", "DOGE", "AVAX",
                   "MATIC", "UNI", "SUSHI", "AAVE", "FIL", "XLM", "ETC", "SXP", "1INCH", "YFI", "ATOM"}


def _is_excluded(base: str, extra: set) -> bool:
    """Stablecoin, wrapped/staked, token berleverage Binance (BTCUP/ETHDOWN/...), dan daftar `exclude` pengguna."""
    b = base.upper()
    if b in STABLES or b in WRAPPED or b in extra:
        return True
    return any(b.endswith(suf) and b[: -len(suf)] in LEVERAGED_STEMS for suf in LEVERAGED_SUFFIX)


# ---------------------------------------------------------------- sumber volume
def _binance_tickers(http_get: Callable, quote: str, timeout: int) -> List[dict]:
    last = "tidak ada host dicoba"
    for host in BINANCE_HOSTS:
        try:
            r = http_get(f"{host}/api/v3/ticker/24hr", timeout=timeout)
            if r.status_code in (451, 403):
                last = f"{host}: HTTP {r.status_code} (geo-block?)"
                continue
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                last = f"{host}: respons kosong"
                continue
            out = []
            for t in data:
                sym = str(t.get("symbol", ""))
                if sym.endswith(quote) and len(sym) > len(quote):
                    out.append({"base": sym[: -len(quote)], "quote_volume": float(t.get("quoteVolume") or 0.0)})
            if out:
                return out
            last = f"{host}: tidak ada pasangan {quote}"
        except Exception as exc:  # noqa: BLE001
            last = f"{host}: {exc}"
    raise UniverseError(f"binance: {last}")


def _ccxt_tickers(exchange_id: str, quote: str, timeout: int, ccxt_factory: Optional[Callable] = None) -> List[dict]:
    try:
        if ccxt_factory:
            ex = ccxt_factory(exchange_id)
        else:
            import ccxt  # type: ignore
            ex = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": timeout * 1000})
        tickers = ex.fetch_tickers()
    except Exception as exc:  # noqa: BLE001
        raise UniverseError(f"ccxt:{exchange_id}: {exc}") from exc
    out = []
    for sym, t in (tickers or {}).items():
        if ":" in sym or not sym.endswith("/" + quote):    # hanya spot BASE/USDT (bukan perpetual BASE/USDT:USDT)
            continue
        qv = t.get("quoteVolume")
        if qv is None and t.get("baseVolume") and (t.get("last") or t.get("close")):
            qv = float(t["baseVolume"]) * float(t.get("last") or t.get("close"))
        out.append({"base": sym.split("/")[0], "quote_volume": float(qv or 0.0)})
    if not out:
        raise UniverseError(f"ccxt:{exchange_id}: tidak ada pasangan spot {quote}")
    return out


def fetch_tickers(source: str, quote: str, timeout: int, http_get: Callable, ccxt_factory: Optional[Callable] = None) -> List[dict]:
    if source == "binance":
        return _binance_tickers(http_get, quote, timeout)
    if source.startswith("ccxt:"):
        return _ccxt_tickers(source.split(":", 1)[1], quote, timeout, ccxt_factory)
    raise UniverseError(f"sumber volume tidak dikenal: {source}")


# ---------------------------------------------------------------- sumber market cap
def fetch_marketcap_ranking(source: str, pool: int, timeout: int, http_get: Callable, env: Optional[dict] = None) -> List[str]:
    """Daftar BASE (huruf besar) berurutan dari market cap terbesar."""
    env = os.environ if env is None else env
    try:
        if source == "cmc":
            key = env.get("CMC_API_KEY", "").strip()
            if not key:
                raise UniverseError("CMC_API_KEY belum diatur (GitHub secret)")
            r = http_get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest",
                         params={"start": 1, "limit": min(pool, 200), "sort": "market_cap", "convert": "USD"},
                         headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"}, timeout=timeout)
            r.raise_for_status()
            rows = sorted(r.json()["data"], key=lambda x: x.get("cmc_rank") or 10 ** 9)
            return [str(x["symbol"]).upper() for x in rows]
        if source == "coingecko":
            r = http_get("https://api.coingecko.com/api/v3/coins/markets",
                         params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": min(pool, 250), "page": 1},
                         headers={"Accept": "application/json"}, timeout=timeout)
            r.raise_for_status()
            rows = sorted(r.json(), key=lambda x: x.get("market_cap_rank") or 10 ** 9)
            return [str(x["symbol"]).upper() for x in rows]
    except UniverseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UniverseError(f"{source}: {exc}") from exc
    raise UniverseError(f"sumber market cap tidak dikenal: {source}")


# ---------------------------------------------------------------- resolver
def resolve_universe(symbols_cfg: Dict[str, Any], http_get: Optional[Callable] = None, ccxt_factory: Optional[Callable] = None,
                     env: Optional[dict] = None) -> Dict[str, Any]:
    """Return {mode, source, top_n, symbols[], detail[], fallback, warnings[]}. Tidak pernah raise: gagal total -> daftar statis."""
    http_get = http_get or requests.get
    ucfg = symbols_cfg.get("universe") or {}
    static = list(symbols_cfg.get("symbols") or [])
    mode = str(ucfg.get("mode", "static"))
    n = int(ucfg.get("top_n", 30))
    quote = str(ucfg.get("quote", "USDT")).upper()
    timeout = int(ucfg.get("timeout_seconds", 25))
    exclude = {str(x).upper() for x in (ucfg.get("exclude") or [])}
    min_vol = float(ucfg.get("min_quote_volume", 0))
    always = list(ucfg.get("always_include") or [])
    if symbols_cfg.get("benchmark") and symbols_cfg["benchmark"] not in always:
        always = [symbols_cfg["benchmark"]] + always
    res: Dict[str, Any] = {"mode": mode, "source": "static", "top_n": n, "symbols": static, "detail": [], "fallback": False, "warnings": []}
    if mode == "static":
        return res
    if mode not in ("top_volume", "top_marketcap"):
        res["warnings"].append(f"universe.mode '{mode}' tidak dikenal -> pakai daftar statis")
        res["fallback"] = True
        return res

    # 1) snapshot ticker (selalu perlu: volume untuk top_volume; daftar pasangan yang tersedia untuk top_marketcap)
    tickers, src_used = None, None
    for src in ucfg.get("volume_sources") or ["binance", "ccxt:bitget", "ccxt:okx"]:
        try:
            tickers = fetch_tickers(src, quote, timeout, http_get, ccxt_factory)
            src_used = src
            log.info("Universe: %d pasangan %s dari %s", len(tickers), quote, src)
            break
        except Exception as exc:  # noqa: BLE001
            res["warnings"].append(f"{src}: {exc}")
            log.warning("Universe: sumber %s gagal: %s", src, exc)
    if not tickers:
        res["fallback"] = True
        res["warnings"].append("semua sumber ticker gagal -> pakai daftar statis")
        return res
    vol = {}
    for t in tickers:
        if not _is_excluded(t["base"], exclude):
            vol[t["base"].upper()] = max(vol.get(t["base"].upper(), 0.0), t["quote_volume"])

    chosen: List[dict] = []
    if mode == "top_volume":
        ranked = sorted(((b, v) for b, v in vol.items() if v >= max(min_vol, 0.0) and v > 0), key=lambda x: -x[1])
        chosen = [{"symbol": f"{b}/{quote}", "rank": i + 1, "quote_volume": v} for i, (b, v) in enumerate(ranked[:n])]
        res["source"] = src_used
    else:
        mc_src = str(ucfg.get("marketcap_source", "coingecko"))
        try:
            order = fetch_marketcap_ranking(mc_src, int(ucfg.get("marketcap_pool", 150)), timeout, http_get, env)
        except Exception as exc:  # noqa: BLE001
            res["warnings"].append(f"marketcap {mc_src}: {exc}")
            if mc_src == "cmc":                          # CMC tanpa key / gagal -> coba CoinGecko
                try:
                    order = fetch_marketcap_ranking("coingecko", int(ucfg.get("marketcap_pool", 150)), timeout, http_get, env)
                    mc_src = "coingecko"
                    res["warnings"].append("CMC gagal -> memakai CoinGecko")
                except Exception as exc2:  # noqa: BLE001
                    res["warnings"].append(f"coingecko: {exc2}")
                    order = []
            else:
                order = []
        if not order:                                    # market cap gagal -> top volume (lebih baik dari daftar statis lama)
            res["warnings"].append("peringkat market cap gagal -> turun ke top_volume")
            res["fallback"] = True
            ranked = sorted(((b, v) for b, v in vol.items() if v > 0), key=lambda x: -x[1])
            chosen = [{"symbol": f"{b}/{quote}", "rank": i + 1, "quote_volume": v} for i, (b, v) in enumerate(ranked[:n])]
            res["source"] = src_used
        else:
            seen = set()
            for base in order:
                if base in seen or base not in vol or vol[base] < min_vol:   # tidak ada pasangan USDT di exchange -> lewati
                    continue
                seen.add(base)
                chosen.append({"symbol": f"{base}/{quote}", "rank": len(chosen) + 1, "quote_volume": vol[base]})
                if len(chosen) >= n:
                    break
            res["source"] = f"{mc_src}+{src_used}"
    syms = [c["symbol"] for c in chosen]
    for a in reversed(always):                           # benchmark / pinned selalu ada, di depan
        if a not in syms:
            syms.insert(0, a)
            chosen.insert(0, {"symbol": a, "rank": 0, "quote_volume": vol.get(a.split("/")[0].upper(), 0.0), "pinned": True})
    if len(chosen) < max(3, n // 3):
        res["fallback"] = True
        res["warnings"].append(f"hanya {len(chosen)} koin lolos filter -> pakai daftar statis")
        return res
    res.update(symbols=syms, detail=chosen)
    res["data_provider_hint"] = src_used if src_used and src_used.startswith("ccxt:") else None
    return res
