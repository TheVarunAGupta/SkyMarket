from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests


MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


@dataclass(frozen=True)
class MarketMapping:
    market_key: str
    city: str
    contract_date: str
    event_id: str
    market_id: str
    token_id: str
    outcome_side: str
    question: str
    bucket_low: float
    bucket_high: float
    best_bid: float
    best_ask: float
    spread: float
    volume: float
    close_time: str
    resolution_time: str
    is_open: bool
    is_tradable: bool
    raw_market_json: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_temp_range(question: str | None) -> tuple[float, float] | None:
    if not question:
        return None
    num = r"(-?\d+(?:\.\d+)?)"
    if re.search(r"or below", question, re.IGNORECASE):
        match = re.search(num + r"[°]?[FC] or below", question, re.IGNORECASE)
        if match:
            return (-999.0, float(match.group(1)))
    if re.search(r"or higher", question, re.IGNORECASE):
        match = re.search(num + r"[°]?[FC] or higher", question, re.IGNORECASE)
        if match:
            return (float(match.group(1)), 999.0)
    match = re.search(r"between " + num + r"-" + num + r"[°]?[FC]", question, re.IGNORECASE)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"be " + num + r"[°]?[FC] on", question, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        return (value, value)
    return None


def hours_to_resolution(end_date_str: str | None) -> float:
    if not end_date_str:
        return 999.0
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except ValueError:
        return 999.0
    return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600.0)


def get_weather_event(city_slug: str, contract_date: date, gamma_host: str) -> dict[str, Any] | None:
    slug = f"highest-temperature-in-{city_slug}-on-{MONTHS[contract_date.month - 1]}-{contract_date.day}-{contract_date.year}"
    response = requests.get(f"{gamma_host}/events", params={"slug": slug}, timeout=(5, 10))
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


def discover_city_markets(city_slug: str, contract_date: date, gamma_host: str) -> list[MarketMapping]:
    event = get_weather_event(city_slug, contract_date, gamma_host)
    if not event:
        return []
    return map_event_to_markets(city_slug, contract_date.isoformat(), event)


def map_event_to_markets(city_slug: str, contract_date: str, event: dict[str, Any]) -> list[MarketMapping]:
    mappings: list[MarketMapping] = []
    event_id = str(event.get("id", ""))
    resolution_time = str(event.get("endDate") or event.get("end_date_iso") or "")

    for market in event.get("markets", []):
        question = str(market.get("question", ""))
        bucket = parse_temp_range(question)
        if not bucket:
            continue
        market_id = str(market.get("id", ""))
        if not market_id:
            continue
        token_id = _extract_yes_token_id(market)
        if not token_id:
            continue

        best_bid = _to_float(market.get("bestBid"), default=_fallback_price(market, 0))
        best_ask = _to_float(market.get("bestAsk"), default=_fallback_price(market, 1))
        if best_bid <= 0 and best_ask <= 0:
            best_bid = _fallback_price(market, 0)
            best_ask = _fallback_price(market, 1)

        is_open = not _truthy(market.get("closed"))
        is_tradable = is_open and not _truthy(market.get("archived")) and _tradable_flag(market)
        spread = round(max(0.0, best_ask - best_bid), 4) if best_ask and best_bid else 0.0
        close_time = str(market.get("endDate") or market.get("end_date_iso") or resolution_time)
        volume = _to_float(market.get("volume"), default=0.0)
        market_key = f"{city_slug}:{contract_date}:{market_id}"

        mappings.append(
            MarketMapping(
                market_key=market_key,
                city=city_slug,
                contract_date=contract_date,
                event_id=event_id,
                market_id=market_id,
                token_id=token_id,
                outcome_side="YES",
                question=question,
                bucket_low=bucket[0],
                bucket_high=bucket[1],
                best_bid=round(best_bid, 4),
                best_ask=round(best_ask, 4),
                spread=spread,
                volume=volume,
                close_time=close_time,
                resolution_time=resolution_time,
                is_open=is_open,
                is_tradable=is_tradable,
                raw_market_json=json.dumps(market, ensure_ascii=True),
            )
        )

    mappings.sort(key=lambda item: item.bucket_low)
    return mappings


def _extract_yes_token_id(market: dict[str, Any]) -> str:
    direct = market.get("clobTokenId") or market.get("token_id")
    if direct:
        return str(direct)

    token_ids = _jsonish(market.get("clobTokenIds"))
    outcomes = _jsonish(market.get("outcomes"))
    if isinstance(token_ids, list) and token_ids:
        if isinstance(outcomes, list):
            for index, outcome in enumerate(outcomes):
                if str(outcome).strip().upper() == "YES" and index < len(token_ids):
                    return str(token_ids[index])
        return str(token_ids[0])
    return ""


def _jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _fallback_price(market: dict[str, Any], index: int) -> float:
    prices = _jsonish(market.get("outcomePrices"))
    if isinstance(prices, list) and len(prices) > index:
        return _to_float(prices[index], default=0.0)
    return 0.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _tradable_flag(market: dict[str, Any]) -> bool:
    flags = [
        market.get("active"),
        market.get("acceptingOrders"),
        market.get("enableOrderBook"),
        market.get("orderBookEnabled"),
    ]
    known = [flag for flag in flags if flag is not None]
    if not known:
        return True
    return any(_truthy(flag) for flag in known)

