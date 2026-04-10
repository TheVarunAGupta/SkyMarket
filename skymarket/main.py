from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .broker import build_broker
from .config import Config, load_config
from .markets import discover_city_markets
from .order_manager import OrderManager
from .storage import Storage
from .strategy import allowed_city_slugs, candidate_contract_dates, generate_trade_ideas


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any]
        if isinstance(record.msg, dict):
            payload = dict(record.msg)
        else:
            payload = {"message": record.getMessage()}
        payload.setdefault("level", record.levelname)
        payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
        return json.dumps(payload, ensure_ascii=True)


def build_logger(level: str) -> logging.Logger:
    logger = logging.getLogger("skymarket")
    logger.handlers.clear()
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def send_alert(config: Config, text: str, logger: logging.Logger) -> None:
    if not config.alert_webhook_url:
        return
    try:
        requests.post(config.alert_webhook_url, json={"text": text}, timeout=(5, 10))
    except Exception as exc:
        logger.error({"event": "alert_failed", "error": str(exc)})


def run_once(config: Config, storage: Storage, manager: OrderManager, logger: logging.Logger) -> None:
    discovered = []
    for city in allowed_city_slugs(config):
        for contract_date in candidate_contract_dates(config):
            try:
                mappings = discover_city_markets(
                    city,
                    datetime.strptime(contract_date, "%Y-%m-%d").date(),
                    config.gamma_host,
                )
            except Exception as exc:
                logger.warning(
                    {
                        "event": "market_discovery_error",
                        "city": city,
                        "contract_date": contract_date,
                        "error": str(exc),
                    }
                )
                continue
            for mapping in mappings:
                storage.upsert_market_mapping(mapping.as_dict())
                discovered.append(mapping)
    logger.info({"event": "market_discovery", "count": len(discovered)})

    available_balance = manager.broker.get_balance()
    ideas = generate_trade_ideas(config, discovered, available_balance)
    logger.info({"event": "signal_generation", "count": len(ideas)})
    submitted = manager.process_trade_ideas(ideas)
    cancelled = manager.cancel_stale_orders()
    updated = manager.refresh_orders()
    logger.info(
        {
            "event": "cycle_complete",
            "submitted": len(submitted),
            "cancelled": len(cancelled),
            "updated": len(updated),
        }
    )


def run_loop(config: Config) -> None:
    logger = build_logger(config.log_level)
    storage = Storage(config.database_path)
    broker = build_broker(config)
    manager = OrderManager(config, storage, broker, logger)

    try:
        reconciliation = manager.reconcile()
        logger.info({"event": "startup", "mode": config.mode, "dry_run": config.dry_run, **reconciliation})
        if config.mode == "live" and not config.dry_run:
            send_alert(config, "SkyMarket live bot started", logger)

        while True:
            try:
                run_once(config, storage, manager, logger)
            except Exception as exc:
                logger.exception({"event": "cycle_error", "error": str(exc)})
                send_alert(config, f"SkyMarket cycle error: {exc}", logger)
            time.sleep(config.poll_interval_seconds)
    finally:
        storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal live-trading Polymarket weather bot")
    parser.add_argument("--config", help="Optional JSON/YAML config file", default=None)
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = build_logger(config.log_level)
    storage = Storage(config.database_path)
    broker = build_broker(config)
    manager = OrderManager(config, storage, broker, logger)

    try:
        reconciliation = manager.reconcile()
        logger.info({"event": "startup", "mode": config.mode, "dry_run": config.dry_run, **reconciliation})
        if args.once:
            run_once(config, storage, manager, logger)
            return
    except Exception as exc:
        logger.exception({"event": "startup_error", "error": str(exc)})
        send_alert(config, f"SkyMarket startup failed: {exc}", logger)
        raise
    finally:
        if args.once:
            storage.close()

    storage.close()
    run_loop(config)


if __name__ == "__main__":
    main()
