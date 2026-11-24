# CryptoEliz Scalp Engine v2 (sctnv2)

Mesin **analisis** trading scalping crypto (BTC + alts terpilih) multi-timeframe, berbasis aturan yang
dioperasionalkan dari filosofi trader @eliz883 (CryptoEliz). Output: laporan Markdown, chart beranotasi,
ringkasan signal (**LONG / SHORT / NO TRADE**) beserta alasan dan rincian skor — siap dijalankan lewat GitHub Actions.

> ⚠️ **Bukan jaminan profit.** Semua angka (jumlah candle, % deviasi, ambang volume, dst.) adalah **hipotesis operasional**
> dari aturan yang aslinya diskresioner. Belum ada bukti edge. Gunakan untuk paper-trading / forward-test dulu.
> Bukan nasihat finansial.

## 0. Yang baru di v2 — indikator pada grafik

Chart (PNG di laporan **dan** chart interaktif di dashboard, tab *Chart* + kartu detail simbol) kini memuat daftar indikator
yang dipakai @eliz883 (catatan 22 Mei 2023 & 15 Apr 2022):

| Indikator | Tampil di chart | Parameter (`config/parameters.yaml → chart_indicators`) |
|---|---|---|
| **EMA 12 / 26 / 100 / 200** | garis di panel harga (kuning, oranye, biru, ungu) | `ema` |
| **Supertrend** | garis hijau (uptrend) / merah (downtrend) | `supertrend: {period: 10, multiplier: 3.0}` (default menurut catatan Eliz) |
| **UTCS≈** | panah ▲ buy / ▼ sell + garis trailing tipis | `utcs: {atr_period: 10, key: 1.0}` — **aproksimasi**, lihat catatan di bawah |
| **Spaceman BTC key level** | garis putus-putus + label kode (PDH/PDL/PDM, DO, PWH/PWL/PWM, WO, PMH/PML/PMM, MO, PQ*, QO, CYH/CYL/CYM, YO, P4H-*, 4H-O, MDAY-H/L/M) | `key_levels` (aktif/nonaktif per grup) |
| **Volume** | batang di dasar panel harga + SMA 20 | `volume` |
| **MACD** | panel sendiri: histogram + garis MACD + sinyal | `macd: {fast: 12, slow: 26, signal: 9}` |
| **RSI** | panel sendiri, zona 70 / 30 | `rsi: {period: 14, overbought: 70, oversold: 30}` |
| **OBV** | panel sendiri + garis EMA 21 (untuk melihat momentum OBV) | `obv: {signal_ema: 21}` |

Chart interaktif (dashboard): geser = pan, Ctrl+scroll / tombol +/− = zoom, klik ganda = reset, arahkan kursor untuk nilai tiap indikator,
chip di atas chart untuk menyalakan/mematikan tiap indikator (pilihan tersimpan di browser). Timeframe 15m / 1h / 4h / 1d.
Data chart dibuat Python (`output/latest/chartdata/*.json`, satu sumber kebenaran dengan PNG) lalu hanya digambar oleh `index.html`.

> **Catatan penting**
> - Indikator di v2 hanya **visual**: tidak ikut skor signal, veto, forward test, maupun backtest (hasil mesin sama seperti sctn v1). Menambahkannya ke skor
>   = perubahan strategi yang harus diuji ulang lewat forward test.
> - **UTCS≈**: sumber indikator UCTS/UTCS asli (CryptoNTez) tertutup (invite-only), jadi yang dipakai adalah pendekatan terbuka
>   (ATR trailing-stop flip ala "UT Bot"). Bukan replika persis. Jika Anda punya rumus aslinya, ganti fungsi `utcs()` di `src/data/indicators.py`.
> - **Spaceman key level**: mengikuti daftar level indikator "Key Levels SpacemanBTC IDWM" di TradingView (Open + Previous High/Low/Mid per periode, Monday range).
>   Dihitung dari candle yang sudah close; level yang periodenya tidak tercakup penuh oleh data dilewati. Level kembar pada harga yang sama digabung labelnya.
> - EMA/MACD yang belum konvergen (awal data) sengaja dikosongkan, bukan ditampilkan sebagai angka palsu.

## 0b. Scanner koin otomatis (v2.1)

Sebelumnya hanya 8 koin karena daftarnya **ditulis manual** di `config/symbols.yaml → symbols`. Sekarang tiap run, `src/data/universe.py`
menentukan sendiri koin yang dianalisis (`config/symbols.yaml → universe`):

| `mode` | Arti |
|---|---|
| `top_volume` *(default, N=30)* | top-N pasangan spot USDT menurut volume 24 jam. Sumber berurutan: `binance` → `ccxt:bitget` → `ccxt:okx` (Binance sering 451/geo-block dari runner GitHub, otomatis lanjut ke Bitget) |
| `top_marketcap` | top-N peringkat market cap lalu dipetakan ke pasangan USDT yang ada di exchange. `marketcap_source: coingecko` (tanpa API key) atau `cmc` (CoinMarketCap; isi secret **`CMC_API_KEY`** di Settings → Secrets → Actions, bila kosong otomatis memakai CoinGecko) |
| `static` | daftar `symbols` manual (perilaku lama) |

- Otomatis dibuang: stablecoin (USDC, FDUSD, DAI, ...), token wrapped/staked (WBTC, stETH, ...), token berleverage (BTCUP, ETHDOWN, ...). Tambahan lewat `exclude`.
- `min_quote_volume` (default 5 juta USDT/24 jam) membuang koin likuiditas tipis — scalping di koin tipis berbahaya.
- BTC/USDT (benchmark) selalu ikut. Jika semua sumber gagal, engine **tidak berhenti**: turun ke daftar `symbols` (dan dashboard menampilkan banner).
- Data OHLCV diutamakan dari exchange yang sama dengan peringkat volume (mis. Bitget), supaya koin hasil scan pasti tersedia.
- Daftar tiap run tersimpan di `output/latest/universe.json` (peringkat + volume) dan ringkasannya ada di `signals.json → universe`.
- Run manual (Actions → *Run workflow*) punya input `universe` dan `top_n` untuk mengganti mode/jumlah tanpa edit file. Di lokal: `ENGINE_UNIVERSE=top_marketcap ENGINE_TOP_N=30 python -m src.main`.
- `config_hash` sekarang **tidak** memasukkan daftar koin/universe (karena berubah tiap run); hanya strategi/TF/risk. Hash lama (v1, 8 koin) tidak sama dengan hash baru — itu normal.
- **Backtest tetap memakai daftar `symbols` statis**: universe historis tidak bisa diputar ulang, dan memakai top-30 *hari ini* untuk masa lalu = survivorship bias.
- Waktu run lebih lama (30 koin × 5 timeframe) dan situs ±20 MB per deploy; batas workflow dinaikkan ke 40 menit. Kurangi `top_n` bila perlu.

## 1. Filosofi → implementasi

| Prinsip | Implementasi di mesin |
|---|---|
| Trade di tepi range, bukan tengah | `range_detector` membuat box + edge zone 20%; entry di tengah range = **veto** (kecuali breakout-retest) |
| Trigger dulu, bukan prediksi | Hanya 3 trigger: deviation+reclaim, breakout+retest, fib 0.75 **dengan reaksi candle**. Limit fib tanpa reaksi = hanya konteks |
| Invalidasi sebelum target | Stop = titik invalidasi struktural (+buffer). Stop > 6% → NO TRADE. RR gabungan < 1.5 → NO TRADE |
| Bias sederhana | `multi_tf_bias` (Weekly+Daily): di atas key level → cari long, di bawah → short. Trade melawan bias = veto |
| Patience is a position | Default **NO TRADE**. Perlu bias + trigger + skor ≥ ambang + lolos semua veto |
| Pisahkan investasi vs trading | Mesin ini hanya trading/scalp. Spot akumulasi di demand zone di luar cakupan |

**Bias (HTF) dan trigger (LTF) dipisah tegas:** Weekly/Daily hanya memberi arah; 4H memberi struktur/range; 1H dan 15m memberi trigger.

**Tidak pernah jadi trigger:** liquidity heatmap, opini makro/konspirasi/komentar non-teknikal. (Tidak diimplementasikan sama sekali.)

## 2. Struktur repo

```
index.html                              # DASHBOARD (GitHub Pages) — statis, tanpa dependensi
.github/workflows/run-analysis.yml      # analisis terjadwal + forward test + build & deploy dashboard
.github/workflows/run-backtest.yml      # backtest walk-forward (manual)
config/{symbols,parameters,risk}.yaml   # SEMUA parameter (tidak ada hard-code)
src/data/        universe.py (scanner koin), fetch_ohlcv.py (Binance REST + ccxt fallback, paging), indicators.py, synthetic.py (demo)
src/analysis/    chart_indicators (EMA/MACD/RSI/OBV/ST/UTCS), key_levels (Spaceman), range_detector, liquidity_deviation, breakout_retest, fibonacci, monday_range,
                 three_tap_wolf, fvg, obv_confirmation, multi_tf_bias, pipeline
src/signal/      signal_engine.py (skor + veto), risk_manager.py (stop/target/size/filter/fee)
src/evaluate/    simulator.py (hasil trade candle-by-candle), stats.py (R, PF, SQN, CI95), forward_test.py
src/backtest/    run.py (replay as-of tanpa lookahead)
src/report/      generate_report.py, chart_generator.py (PNG multi-panel), chart_data.py (JSON chart interaktif)
src/notify.py    Telegram / Discord (opsional)
src/site_builder.py  # rakit folder site/ untuk Pages
tests/           unit + smoke test (termasuk indikator, key level, ekspor chart)
output/          signal_log.csv (jurnal), forward_test.json, backtest/ (di-commit); latest/ (tidak di-commit)
```

## 3. Definisi operasional (hipotesis — semua bisa di-tune di `config/parameters.yaml`)

| Konsep | Definisi default |
|---|---|
| **Range** | Window 48–168 candle H1 (4H: 30–90). ≥2 pivot menyentuh tiap tepi (toleransi 0.35%), lebar 1.5–12%, drift < 0.6 × tinggi box, ≤3% close di luar box. `exclude_recent` candle terbaru tidak ikut membentuk box (agar deviasi/breakout terbaca) |
| **Deviation + reclaim** | Wick tembus level ≥0.15% (maks 3%), candle sebelumnya masih di dalam, close kembali di dalam ≤4 candle (H1). Entry = retest level ±0.20%; stop = di luar ekstrem deviasi; invalid jika ada close melewati ekstrem |
| **Breakout + retest** | Close lewat level ≥0.30%, body ≥0.6 ATR, volume ≥1.2× SMA20, bertahan 2 candle (kalau tidak → itu deviation). Entry di retest ±0.20% |
| **Fib 0.75** | Impulse ≥5% dari pivot; zona 0.71–0.79; invalid di 0.90. Trigger hanya jika zona tersentuh + candle terakhir searah |
| **Monday range** | High/Low candle harian Senin (UTC) yang sudah close; fallback ke Senin minggu lalu |
| **Three-tap** | 3 pivot berurutan naik/turun (langkah 0.15–3%); tap-3 gagal: close kembali melewati tap-2 |
| **Wolf** | 5 pivot selang-seling, garis 1-3 & 2-4 konvergen, titik 5 overshoot garis 1-3 lalu bertahan |
| **FVG** | Gap 3 candle ≥0.25 ATR, belum terisi penuh; hanya konfirmasi |
| **OBV** | Divergensi pivot-ke-pivot; pola V: ayunan ≥3× rata-rata volume, pulih ≥70% |
| **Volume rendah** | Rata-rata 3 candle H1 terakhir < 0.5× baseline 50 candle → blok entry |

## 4. Scoring (transparan)

Setiap setup (arah × trigger) dinilai sendiri; item & poin ditampilkan di laporan.

`bias searah +2` · `trigger: deviation +3 / breakout-retest +2 / fib +2` · `harga di entry zone +1` ·
`konfluensi (tepi range 4H, Monday level, fib zone) +1 each` · `konfirmasi (FVG, OBV div, OBV-V, three-tap, wolf, volume spike) +1 each` ·
`konflik dengan bias BTC −1` (untuk alts).

Lolos jika **skor ≥ 6**, ada ≥1 konfluensi/konfirmasi tambahan, dan tidak ada veto:
bias berlawanan · entry di tengah range · status `late`/`invalidated`/`deep_retest` · level pending > 3 ATR ·
stop > 6% · RR gabungan < 1.5 · volume rendah · menjelang/sesudah monthly close · event blackout manual.

## 5. Manajemen posisi (risk.yaml)

Stop struktural + buffer (maks 6%); TP1 di level struktur terdekat dengan R ≥ 1.2 (fallback 1.5R), tutup 60%;
moonbag ke TP2 dengan stop dipindah ke BE+0.1%; leverage disarankan sedemikian hingga jarak likuidasi ≥ 2× jarak stop
(maks 10x). Lebih baik miss daripada stop lebar/likuidasi.

**Event besar (FOMC dll):** isi manual di `risk.yaml → filters.event_blackouts` (UTC). Tidak ada tanggal yang di-hardcode.

## 6. Setup GitHub (urutan)

1. Upload seluruh isi folder ini ke **root** repo (`index.html`, `config/`, `src/`, `.github/` harus langsung di root, bukan di dalam
   subfolder `sctnv2/`). Folder `.github` bersifat tersembunyi dan sering terlewat saat drag-and-drop di web — cara paling aman lewat git:
   ```bash
   unzip sctnv2.zip && cd sctnv2
   git init -b main && git add -A && git commit -m "init"
   git remote add origin https://github.com/triasnugra/sctnv2.git
   git push -u origin main --force
   ```
   Pastikan di GitHub tab **Actions** terlihat workflow `run-analysis` dan `run-backtest`.
2. **Settings → Actions → General → Workflow permissions → Read and write permissions.**
3. **Settings → Pages → Build and deployment → Source: GitHub Actions** (WAJIB — tanpa ini job `deploy` gagal dan situs tidak terbit).
4. Push pertama otomatis menjalankan `run-analysis`. Bisa juga manual: **Actions → run-analysis → Run workflow** (centang `demo` untuk uji data sintetis).
5. Dashboard: `https://triasnugra.github.io/sctnv2/` (muncul setelah job **deploy** hijau; lihat link di ringkasan run).
6. (Opsional) Notifikasi: *Settings → Secrets and variables → Actions → New repository secret*:
   `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, dan/atau `DISCORD_WEBHOOK_URL`. Hanya signal **baru** yang dikirim.
7. (Disarankan) **Actions → run-backtest** (default 45 hari). Setelah selesai, workflow ini otomatis memicu `run-analysis`
   supaya dashboard memuat hasil backtest (matikan lewat input `publish`).

Jadwal default tiap jam (menit ke-5). Ubah di `run-analysis.yml` (`5 */4 * * *` = tiap 4 jam).
Job `deploy` hanya berjalan dari branch default (`main`) karena aturan environment `github-pages`.

### Apa yang di-commit ke repo
Hanya state kecil: `output/signal_log.csv`, `output/forward_test.json`, `output/backtest/*`. Chart PNG & laporan
**tidak** di-commit (dikirim ke dashboard lewat Pages artifact) supaya riwayat git tidak membengkak.

### Lokal
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
python -m src.main --demo                        # data SINTETIS (tanpa internet)
python -m src.main                               # live
python -m src.evaluate.forward_test              # evaluasi jurnal
python -m src.backtest.run --days 45             # backtest (tambah --demo untuk uji)
python -m src.site_builder && python -m http.server -d site 8000   # dashboard di http://localhost:8000
```
Dashboard TIDAK bisa dibuka lewat `file://` (browser memblokir fetch); gunakan server lokal di atas.

### Sumber data
`binance_rest` mencoba beberapa host Binance (termasuk `data-api.binance.vision`), lalu fallback `ccxt:okx`, `ccxt:kucoin`
(ubah di `symbols.yaml → data.providers`). Binance sering memblokir IP US (HTTP 451). Satu simbol selalu diambil
dari **satu** provider untuk semua TF. Hanya candle yang sudah close yang dianalisis.

## 7. Evaluasi: forward test & backtest

- **Jurnal** (`signal_log.csv`): hanya signal LONG/SHORT yang *baru pertama kali* muncul (dedup per kejadian setup lewat `signal_id`). Mode demo tidak menulis jurnal.
- **Forward test** (`forward_test.json`): tiap signal disimulasikan dengan candle 15m aktual. Aturan konservatif:
  stop & target di candle yang sama → stop dulu; limit pending batal bila TP1 tercapai sebelum terisi / lewat 24 jam;
  TP1 menutup 60% lalu stop ke BE+; timeout 72 jam = mark-to-market; fee+slippage kasar 0.10% dikonversi ke R.
- **Statistik**: expectancy (R), win rate, profit factor, SQN, CI95 expectancy, max drawdown (R).
  Status **UNVERIFIABLE** sampai ≥150 trade & ≥20 minggu; baru setelah itu PASS/FAIL (CI95 bawah > 0 dan PF ≥ 1.2).
- **Backtest**: replay per jam; pada tiap titik mesin hanya melihat candle yang sudah close saat itu (tanpa lookahead),
  memakai kode analisis & simulator yang sama dengan live. Hasilnya bukan bukti edge — sampel kecil, signal berkorelasi,
  parameter adalah hipotesis. Jangan tune parameter berdasarkan satu backtest (data snooping); catat `config_hash`.
- **Filter fee**: signal dengan stop terlalu rapat (fee > 0.15R) di-veto — pada stop sempit fee bisa memakan seluruh edge.

## 8. Keterbatasan
- Aturan diskresioner tidak sepenuhnya bisa direpresentasikan; hasil bisa berbeda dari penilaian trader aslinya.
- Simulasi tidak memodelkan funding, slippage nyata, partial fill, atau gap likuiditas.
- Jadwal cron GitHub bisa tertunda; signal H1/15m bisa basi — selalu cek chart & harga terkini sebelum bertindak.
- Estimasi likuidasi kasar; fee/funding/slippage tidak dimodelkan.
