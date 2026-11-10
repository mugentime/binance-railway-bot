# Martingale Autotune Log

Hourly autonomous optimizer for the live martingale bot (binance-railway-bot, MAIN account).
One line per run. TP=10%/SL=4% are fixed and never appear as a lever here — only
entry rules, pair selection, and (once the 50% real-win-rate gate is met) martingale
sizing are in scope. Format: `UTC timestamp | change | real data basis | gate status | notes`.

- 2026-11-09T01:11Z | DEPLOYED repeat-loser cull (ENABLE_LOSER_CULL=True, CULL_MIN_TRADES=20, CULL_MIN_WINRATE=0.35, CULL_SEED_RETIRED=[CHIP,MAGMA,ORDI,PROM,Q,APR]) | real 2026-08-30→11-08 n=844 closes: 37% win, net −$4.65; backtest replay post-cull: net +$54.37 (optimistic, freed-slot PnL assumed $0) | gate NOT met (37% < 50%) | commit 0d3ac9c, deploy SUCCESS.
- 2026-11-10T02:40Z | NO CHANGE — data too thin to justify one | only 26 real closes retrievable this run (Railway deploy-log retention ≈14d covers 2026-10-27→11-10 only; no volume/state.json file access from this sandbox): 6W/20L = 23.1% win, net −$10.87 (avg −$0.42/trade), clearly negative expectancy; post-cull subset (since 11-09T01:17Z) n=5: 1W/4L, net −$2.48 — too small to judge the cull yet (symbols need CULL_MIN_TRADES=20 before eligible). No crash/error in the Nov6→Nov9 zero-trade gap (confirmed via logs: selective entries + overnight pause, not a bug). | gate NOT met | made no entry/pair/martingale change; live deploy verified healthy (commit 0d3ac9c, SUCCESS, EDGEUSDT position holding normally, no traceback). Flag for future runs: need a real ≥100-trade sample — either widen log query range once more history accrues, or add an authenticated export path reachable from this sandbox.
