# SkyMarket

Smallest practical path from the original paper weather bot to a restart-safe live Polymarket weather trader.

The repo now keeps the existing `bot_v2.py` forecast and signal logic as the strategy baseline, but moves the live path into a tiny package with:
- typed config loading from `.env` plus optional JSON/YAML
- Polymarket market discovery and YES-token mapping
- a real broker adapter using `py-clob-client`
- SQLite persistence for signals, orders, fills, positions, and reconciliation
- conservative restart recovery and hard risk controls
- one live-ready entrypoint

## Repo Audit Summary

What already existed:
- `bot_v2.py` had the useful core: city/station mapping, weather forecast fetching, Polymarket event discovery by slug, bucket parsing, EV/Kelly sizing, and paper-style state handling.
- `bot_v1.py` was a smaller prototype and not a good live-trading base.

What was missing:
- no reproducible dependency setup
- no typed config or `.env` flow
- no real execution layer
- no durable state for orders/positions
- no restart reconciliation
- no hard live-mode safety gates

What changed:
- added the `skymarket` package for config, markets, strategy, broker, storage, order management, and the new entrypoint
- added SQLite-backed persistence
- added focused tests for config, market mapping, risk checks, persistence, and reconciliation
- added `.env.example` and a new install/run flow

## Package Layout

- `skymarket/config.py`: typed config loader and live-mode validation
- `skymarket/markets.py`: Polymarket event lookup and tradable YES-token mapping
- `skymarket/strategy.py`: preserved weather forecast and signal logic extracted from `bot_v2.py`
- `skymarket/broker.py`: paper broker plus live Polymarket broker
- `skymarket/storage.py`: thin SQLite persistence layer
- `skymarket/order_manager.py`: reconciliation, risk checks, dedupe, submit, stale cancel
- `skymarket/main.py`: single runnable bot entrypoint

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

The code still supports `config.json` or YAML configs if you want them, but `.env` is the default and simplest path.

## Config

Important variables:

```dotenv
MODE=paper
DRY_RUN=true
LIVE_TRADING_ENABLED=false
KILL_SWITCH=false

POLY_PRIVATE_KEY=
POLY_FUNDER=
POLY_SIGNATURE_TYPE=0

ALLOWED_CITIES=nyc,chicago,miami,dallas,seattle,atlanta

MAX_ORDER_SIZE=20
MAX_POSITION_PER_MARKET=20
MAX_TOTAL_EXPOSURE=100
MAX_DAILY_LOSS=50
MIN_EDGE=0.10
MAX_SPREAD=0.03
MAX_ENTRY_PRICE=0.45

POLL_INTERVAL_SECONDS=3600
MONITOR_INTERVAL_SECONDS=600
STALE_ORDER_SECONDS=300
DATABASE_PATH=data/skymarket.db
```

Live mode fails fast if required wallet settings are missing.

Assumptions baked into v1 live mode:
- only the `YES` side of the matched temperature bucket is traded
- direct EOA signing is the default path
- nonzero `POLY_SIGNATURE_TYPE` is supported, and `POLY_FUNDER` becomes required in that case
- entries use aggressive limit buys at the current best ask

## Usage

Paper mode, one cycle:

```bash
python -m skymarket.main --once
```

Paper mode, continuous:

```bash
python -m skymarket.main
```

Live mode:

```bash
MODE=live \
DRY_RUN=false \
LIVE_TRADING_ENABLED=true \
KILL_SWITCH=false \
python -m skymarket.main
```

Optional config file:

```bash
python -m skymarket.main --config config.yaml --once
```

## What The Live Bot Does

Each cycle:
1. loads config and opens the SQLite database
2. reconciles local state against broker open orders, fills, and positions
3. discovers weather markets by the existing slug-based path
4. maps matching buckets to actual tradable YES token ids
5. generates signals from the preserved forecast/EV/Kelly logic
6. blocks anything that fails hard risk checks
7. places orders through the paper broker or Polymarket broker
8. persists signals, orders, fills, and positions for restart safety
9. cancels stale unfilled orders conservatively

## Safety Warnings

- Start in paper mode first.
- Verify wallet funding and token allowance setup externally before the first live run.
- Live mode requires both `MODE=live` and `LIVE_TRADING_ENABLED=true`.
- Keep `KILL_SWITCH=true` until wallet setup and risk limits are confirmed.
- The first live version focuses on safe entry, persistence, and restart behavior. It does not yet implement advanced live exits or full lifecycle portfolio management.

## Tests

Run:

```bash
pytest tests
```

Current focused coverage:
- config loading and live validation
- market mapping to tradable YES tokens
- risk guard behavior
- SQLite persistence round-trip
- startup reconciliation basics

## Notes

- `bot_v2.py` remains in the repo as the original reference implementation the new strategy module was extracted from.
- `config.json` legacy settings still load for backward compatibility where practical.
- Assumptions that could matter live are kept brief in code comments or this README instead of adding more architecture up front.

## Next Improvements

- add stronger live exit logic for open positions
- improve reconciliation against broker state for partially filled or externally modified orders
- add wallet allowance and auth preflight checks before entering the main loop
- improve size selection using real order book depth instead of only top-of-book prices
