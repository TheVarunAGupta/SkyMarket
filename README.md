# 🌤 Weather Trading Bot — Polymarket

Automated weather market trading bot for Polymarket. Finds mispriced temperature outcomes using Open-Meteo forecasts, filters trades with **Expected Value** analysis, and sizes positions with the **Kelly Criterion**.

No SDK. No black box. ~400 lines of pure Python.

---

## How It Works

Polymarket runs markets like *"Will the highest temperature in NYC be between 40–41°F on March 4?"* These markets are often mispriced — the forecast says 78% likely, but the market is trading at 8 cents.

The bot:
1. Fetches 4-day forecasts from [Open-Meteo](https://open-meteo.com) (free, no API key)
2. Finds the matching temperature bucket on Polymarket
3. Calculates **Expected Value** — skips the trade if EV is negative
4. Calculates **Kelly Criterion** — sizes the position based on edge strength
5. Runs a full **$1,000 simulation** against real market prices before you risk anything

---

## Kelly + EV Logic

**Expected Value** — is this trade mathematically profitable?
```
EV = (our_probability × net_payout) − (1 − our_probability)
```

**Kelly Criterion** — how much of the balance to bet?
```
Kelly % = (p × b − q) / b
```
We use **fractional Kelly (25%)** and cap each position at **10% of balance**.

---

## Installation

```bash
git clone https://github.com/alteregoeth-ai/weatherbot
cd weatherbot
pip install requests
```

Add your settings to `config.json`:
```json
{
  "entry_threshold": 0.15,
  "exit_threshold": 0.45,
  "locations": "NYC,Chicago,Seattle,Atlanta,Dallas,Miami"
}
```

---

## Usage

```bash
# Paper mode — shows signals + Kelly/EV analysis, no trades
python weather_bot_v2.py

# Simulation mode — executes trades, updates virtual $1,000 balance
python weather_bot_v2.py --live

# Show open positions and PnL
python weather_bot_v2.py --positions

# Reset simulation back to $1,000
python weather_bot_v2.py --reset
```

---

## Dashboard

Open `sim_dashboard.html` in any browser to see the simulation in real time:

- Balance chart with floating +/- labels on each trade
- Open positions with Kelly %, EV, and price progress bar
- Full trade history with W/L tracking
- No server needed — pure HTML/JS

---

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `entry_threshold` | `0.15` | Buy below this price |
| `exit_threshold` | `0.45` | Sell above this price |
| `locations` | `NYC,...` | Cities to scan |
| `max_trades_per_run` | `5` | Max trades per run |
| `min_hours_to_resolution` | `2` | Skip if resolves too soon |

---

## Live Trading

The bot runs in simulation mode by default. To execute real trades, add Polymarket CLOB integration:

```bash
pip install py-clob-client
```

Then replace the paper mode line in `weather_bot_v2.py` with your CLOB buy function. Full guide in the article linked below.

---

## APIs Used

| API | Auth | Purpose |
|---|---|---|
| [Open-Meteo](https://open-meteo.com) | None | Weather forecasts |
| [Polymarket Gamma](https://gamma-api.polymarket.com) | None | Market data |
| [Polymarket CLOB](https://clob.polymarket.com) | Wallet key | Live trading (optional) |

---

## Disclaimer

This is not financial advice. Prediction markets carry real risk. Run the simulation thoroughly before committing real capital.
