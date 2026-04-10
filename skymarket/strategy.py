from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import Config
from .markets import MarketMapping, hours_to_resolution


LOCATIONS = {
    "nyc": {"lat": 40.7772, "lon": -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago": {"lat": 41.9742, "lon": -87.9073, "name": "Chicago", "station": "KORD", "unit": "F", "region": "us"},
    "miami": {"lat": 25.7959, "lon": -80.2870, "name": "Miami", "station": "KMIA", "unit": "F", "region": "us"},
    "dallas": {"lat": 32.8471, "lon": -96.8518, "name": "Dallas", "station": "KDAL", "unit": "F", "region": "us"},
    "seattle": {"lat": 47.4502, "lon": -122.3088, "name": "Seattle", "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta": {"lat": 33.6407, "lon": -84.4277, "name": "Atlanta", "station": "KATL", "unit": "F", "region": "us"},
    "london": {"lat": 51.5048, "lon": 0.0495, "name": "London", "station": "EGLC", "unit": "C", "region": "eu"},
    "paris": {"lat": 48.9962, "lon": 2.5979, "name": "Paris", "station": "LFPG", "unit": "C", "region": "eu"},
    "munich": {"lat": 48.3537, "lon": 11.7750, "name": "Munich", "station": "EDDM", "unit": "C", "region": "eu"},
    "ankara": {"lat": 40.1281, "lon": 32.9951, "name": "Ankara", "station": "LTAC", "unit": "C", "region": "eu"},
    "seoul": {"lat": 37.4691, "lon": 126.4505, "name": "Seoul", "station": "RKSI", "unit": "C", "region": "asia"},
    "tokyo": {"lat": 35.7647, "lon": 140.3864, "name": "Tokyo", "station": "RJTT", "unit": "C", "region": "asia"},
    "shanghai": {"lat": 31.1443, "lon": 121.8083, "name": "Shanghai", "station": "ZSPD", "unit": "C", "region": "asia"},
    "singapore": {"lat": 1.3502, "lon": 103.9940, "name": "Singapore", "station": "WSSS", "unit": "C", "region": "asia"},
    "lucknow": {"lat": 26.7606, "lon": 80.8893, "name": "Lucknow", "station": "VILK", "unit": "C", "region": "asia"},
    "tel-aviv": {"lat": 32.0114, "lon": 34.8867, "name": "Tel Aviv", "station": "LLBG", "unit": "C", "region": "asia"},
    "toronto": {"lat": 43.6772, "lon": -79.6306, "name": "Toronto", "station": "CYYZ", "unit": "C", "region": "ca"},
    "sao-paulo": {"lat": -23.4356, "lon": -46.4731, "name": "Sao Paulo", "station": "SBGR", "unit": "C", "region": "sa"},
    "buenos-aires": {"lat": -34.8222, "lon": -58.5358, "name": "Buenos Aires", "station": "SAEZ", "unit": "C", "region": "sa"},
    "wellington": {"lat": -41.3272, "lon": 174.8052, "name": "Wellington", "station": "NZWN", "unit": "C", "region": "oc"},
}

TIMEZONES = {
    "nyc": "America/New_York",
    "chicago": "America/Chicago",
    "miami": "America/New_York",
    "dallas": "America/Chicago",
    "seattle": "America/Los_Angeles",
    "atlanta": "America/New_York",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "munich": "Europe/Berlin",
    "ankara": "Europe/Istanbul",
    "seoul": "Asia/Seoul",
    "tokyo": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai",
    "singapore": "Asia/Singapore",
    "lucknow": "Asia/Kolkata",
    "tel-aviv": "Asia/Jerusalem",
    "toronto": "America/Toronto",
    "sao-paulo": "America/Sao_Paulo",
    "buenos-aires": "America/Argentina/Buenos_Aires",
    "wellington": "Pacific/Auckland",
}

SIGMA_F = 2.0
SIGMA_C = 1.2


@dataclass(frozen=True)
class TradeIdea:
    signal_key: str
    market_key: str
    city: str
    contract_date: str
    market_id: str
    token_id: str
    question: str
    price: float
    bid: float
    spread: float
    volume: float
    bucket_low: float
    bucket_high: float
    forecast_temp: float
    forecast_source: str
    probability: float
    edge: float
    kelly_fraction: float
    size_usd: float
    shares: float
    hours_left: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def in_bucket(forecast: float, t_low: float, t_high: float) -> bool:
    if t_low == t_high:
        return round(float(forecast)) == round(t_low)
    return t_low <= float(forecast) <= t_high


def bucket_prob(forecast: float, t_low: float, t_high: float, sigma: float) -> float:
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / sigma)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / sigma)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0


def calc_ev(probability: float, price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return round(probability * (1.0 / price - 1.0) - (1.0 - probability), 4)


def calc_kelly(probability: float, price: float, config: Config) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    b = 1.0 / price - 1.0
    fraction = (probability * b - (1.0 - probability)) / b
    return round(min(max(0.0, fraction) * config.kelly_fraction, 1.0), 4)


def bet_size(kelly: float, balance: float, config: Config) -> float:
    raw = kelly * balance
    return round(min(raw, config.max_order_size), 2)


def allowed_city_slugs(config: Config) -> list[str]:
    if config.allowed_cities:
        return [slug for slug in config.allowed_cities if slug in LOCATIONS]
    return list(LOCATIONS.keys())


def get_ecmwf(city_slug: str, dates: list[str]) -> dict[str, float]:
    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    result: dict[str, float] = {}
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=temperature_2m_max&temperature_unit={temp_unit}"
        f"&forecast_days=7&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        "&models=ecmwf_ifs025&bias_correction=true"
    )
    for attempt in range(3):
        try:
            data = requests.get(url, timeout=(5, 10)).json()
            if "error" not in data:
                for day, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                    if day in dates and temp is not None:
                        result[day] = round(temp, 1) if unit == "C" else round(temp)
            break
        except Exception:
            if attempt < 2:
                time.sleep(2)
    return result


def get_hrrr(city_slug: str, dates: list[str]) -> dict[str, float]:
    loc = LOCATIONS[city_slug]
    if loc["region"] != "us":
        return {}
    result: dict[str, float] = {}
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        "&daily=temperature_2m_max&temperature_unit=fahrenheit"
        f"&forecast_days=3&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        "&models=gfs_seamless"
    )
    for attempt in range(3):
        try:
            data = requests.get(url, timeout=(5, 10)).json()
            if "error" not in data:
                for day, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                    if day in dates and temp is not None:
                        result[day] = round(temp)
            break
        except Exception:
            if attempt < 2:
                time.sleep(2)
    return result


def get_metar(city_slug: str) -> float | None:
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    try:
        data = requests.get(
            f"https://aviationweather.gov/api/data/metar?ids={station}&format=json",
            timeout=(5, 8),
        ).json()
    except Exception:
        return None
    if isinstance(data, list) and data:
        temp_c = data[0].get("temp")
        if temp_c is not None:
            if unit == "F":
                return round(float(temp_c) * 9 / 5 + 32)
            return round(float(temp_c), 1)
    return None


def take_forecast_snapshot(city_slug: str, dates: list[str]) -> dict[str, dict[str, Any]]:
    now_str = datetime.now(timezone.utc).isoformat()
    ecmwf = get_ecmwf(city_slug, dates)
    hrrr = get_hrrr(city_slug, dates)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshots: dict[str, dict[str, Any]] = {}

    for day in dates:
        snap: dict[str, Any] = {
            "ts": now_str,
            "ecmwf": ecmwf.get(day),
            "hrrr": hrrr.get(day),
            "metar": get_metar(city_slug) if day == today else None,
        }
        if LOCATIONS[city_slug]["region"] == "us" and snap["hrrr"] is not None:
            snap["best"] = snap["hrrr"]
            snap["best_source"] = "hrrr"
        elif snap["ecmwf"] is not None:
            snap["best"] = snap["ecmwf"]
            snap["best_source"] = "ecmwf"
        else:
            snap["best"] = None
            snap["best_source"] = None
        snapshots[day] = snap
    return snapshots


def generate_trade_ideas(
    config: Config,
    mappings: list[MarketMapping],
    available_balance: float,
) -> list[TradeIdea]:
    by_city_date: dict[tuple[str, str], list[MarketMapping]] = {}
    for mapping in mappings:
        by_city_date.setdefault((mapping.city, mapping.contract_date), []).append(mapping)

    ideas: list[TradeIdea] = []
    for (city, contract_date), market_group in by_city_date.items():
        snapshot = take_forecast_snapshot(city, [contract_date]).get(contract_date, {})
        forecast_temp = snapshot.get("best")
        best_source = snapshot.get("best_source") or "ecmwf"
        if forecast_temp is None:
            continue

        matching = next((item for item in market_group if in_bucket(forecast_temp, item.bucket_low, item.bucket_high)), None)
        if not matching or not matching.is_open or not matching.is_tradable:
            continue

        hours_left = hours_to_resolution(matching.close_time or matching.resolution_time)
        if hours_left < config.min_hours or hours_left > config.max_hours:
            continue
        if matching.volume < config.min_volume:
            continue
        if matching.best_ask <= 0 or matching.best_ask >= config.max_entry_price:
            continue

        sigma = SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C
        probability = bucket_prob(forecast_temp, matching.bucket_low, matching.bucket_high, sigma)
        edge = calc_ev(probability, matching.best_ask)
        if edge < config.min_edge or matching.spread > config.max_spread:
            continue
        kelly = calc_kelly(probability, matching.best_ask, config)
        size = bet_size(kelly, available_balance, config)
        if size < 1.0:
            continue
        shares = round(size / matching.best_ask, 4)
        signal_key = f"{matching.market_key}:{snapshot.get('ts', '')}"
        ideas.append(
            TradeIdea(
                signal_key=signal_key,
                market_key=matching.market_key,
                city=city,
                contract_date=contract_date,
                market_id=matching.market_id,
                token_id=matching.token_id,
                question=matching.question,
                price=matching.best_ask,
                bid=matching.best_bid,
                spread=matching.spread,
                volume=matching.volume,
                bucket_low=matching.bucket_low,
                bucket_high=matching.bucket_high,
                forecast_temp=float(forecast_temp),
                forecast_source=best_source,
                probability=round(probability, 4),
                edge=edge,
                kelly_fraction=kelly,
                size_usd=size,
                shares=shares,
                hours_left=round(hours_left, 2),
            )
        )
    return ideas


def candidate_contract_dates(config: Config) -> list[str]:
    now = datetime.now(timezone.utc)
    return [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(config.weather_horizon_days)]

