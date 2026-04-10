from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return [str(value).strip().lower()]


def _read_json_or_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("PyYAML is required to load YAML config files") from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(dotenv_path, override=False)


@dataclass(frozen=True)
class Config:
    mode: str = "paper"
    dry_run: bool = True
    live_trading_enabled: bool = False
    kill_switch: bool = True
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    data_api_host: str = "https://data-api.polymarket.com"
    chain_id: int = 137
    private_key: str = ""
    funder: str = ""
    signature_type: int = 0
    allowed_cities: tuple[str, ...] = ()
    max_order_size: float = 20.0
    max_position_per_market: float = 20.0
    max_total_exposure: float = 100.0
    max_daily_loss: float = 50.0
    min_edge: float = 0.10
    max_spread: float = 0.03
    max_entry_price: float = 0.45
    min_hours: float = 2.0
    max_hours: float = 72.0
    min_volume: float = 500.0
    poll_interval_seconds: int = 3600
    monitor_interval_seconds: int = 600
    stale_order_seconds: int = 300
    weather_horizon_days: int = 4
    starting_balance: float = 10000.0
    kelly_fraction: float = 0.25
    calibration_min: int = 30
    vc_key: str = ""
    alert_webhook_url: str = ""
    database_path: str = "data/skymarket.db"
    log_level: str = "INFO"

    @property
    def is_live(self) -> bool:
        return self.mode.lower() == "live" and not self.dry_run

    def validate(self) -> None:
        mode = self.mode.lower()
        if mode not in {"paper", "live"}:
            raise ValueError("MODE must be 'paper' or 'live'")
        if self.max_order_size <= 0:
            raise ValueError("MAX_ORDER_SIZE must be > 0")
        if self.max_position_per_market <= 0:
            raise ValueError("MAX_POSITION_PER_MARKET must be > 0")
        if self.max_total_exposure <= 0:
            raise ValueError("MAX_TOTAL_EXPOSURE must be > 0")
        if self.max_daily_loss <= 0:
            raise ValueError("MAX_DAILY_LOSS must be > 0")
        if self.poll_interval_seconds <= 0 or self.monitor_interval_seconds <= 0:
            raise ValueError("Polling intervals must be > 0")
        if mode == "live":
            missing = []
            if not self.private_key:
                missing.append("POLY_PRIVATE_KEY")
            if not self.clob_host:
                missing.append("POLY_CLOB_HOST")
            if not self.chain_id:
                missing.append("POLY_CHAIN_ID")
            if self.signature_type != 0 and not self.funder:
                missing.append("POLY_FUNDER")
            if not self.live_trading_enabled:
                missing.append("LIVE_TRADING_ENABLED=true")
            if missing:
                raise ValueError(f"Missing required live settings: {', '.join(missing)}")


def _legacy_defaults(base: dict[str, Any]) -> dict[str, Any]:
    if not base:
        return {}
    return {
        "STARTING_BALANCE": base.get("balance"),
        "MAX_ORDER_SIZE": base.get("max_bet"),
        "MIN_EDGE": base.get("min_ev"),
        "MAX_ENTRY_PRICE": base.get("max_price"),
        "MIN_VOLUME": base.get("min_volume"),
        "MIN_HOURS": base.get("min_hours"),
        "MAX_HOURS": base.get("max_hours"),
        "KELLY_FRACTION": base.get("kelly_fraction"),
        "POLL_INTERVAL_SECONDS": base.get("scan_interval"),
        "CALIBRATION_MIN": base.get("calibration_min"),
        "VC_KEY": base.get("vc_key"),
        "MAX_SPREAD": base.get("max_slippage"),
    }


def load_config(config_path: str | None = None) -> Config:
    repo_root = Path.cwd()
    _load_dotenv(repo_root / ".env")

    file_data: dict[str, Any] = {}
    if config_path:
        file_data = _read_json_or_yaml(Path(config_path))
    else:
        for candidate in ("config.yaml", "config.yml", "config.json"):
            candidate_path = repo_root / candidate
            if candidate_path.exists():
                file_data = _read_json_or_yaml(candidate_path)
                break

    merged = _legacy_defaults(file_data)
    merged.update({k.upper(): v for k, v in file_data.items()})

    def pick(name: str, default: Any = None) -> Any:
        env_value = os.getenv(name)
        if env_value is not None:
            return env_value
        value = merged.get(name, default)
        return default if value is None else value

    allowed_cities = tuple(_parse_list(pick("ALLOWED_CITIES", [])))
    mode = str(pick("MODE", "paper")).lower()
    dry_run = _parse_bool(pick("DRY_RUN", mode != "live"), default=(mode != "live"))

    config = Config(
        mode=mode,
        dry_run=dry_run,
        live_trading_enabled=_parse_bool(pick("LIVE_TRADING_ENABLED", False)),
        kill_switch=_parse_bool(pick("KILL_SWITCH", mode != "paper"), default=(mode != "paper")),
        clob_host=str(pick("POLY_CLOB_HOST", "https://clob.polymarket.com")),
        gamma_host=str(pick("POLY_GAMMA_HOST", "https://gamma-api.polymarket.com")),
        data_api_host=str(pick("POLY_DATA_API_HOST", "https://data-api.polymarket.com")),
        chain_id=int(pick("POLY_CHAIN_ID", 137)),
        private_key=str(pick("POLY_PRIVATE_KEY", "")),
        funder=str(pick("POLY_FUNDER", "")),
        signature_type=int(pick("POLY_SIGNATURE_TYPE", 0)),
        allowed_cities=allowed_cities,
        max_order_size=float(pick("MAX_ORDER_SIZE", 20.0)),
        max_position_per_market=float(pick("MAX_POSITION_PER_MARKET", pick("MAX_ORDER_SIZE", 20.0))),
        max_total_exposure=float(pick("MAX_TOTAL_EXPOSURE", 100.0)),
        max_daily_loss=float(pick("MAX_DAILY_LOSS", 50.0)),
        min_edge=float(pick("MIN_EDGE", 0.10)),
        max_spread=float(pick("MAX_SPREAD", 0.03)),
        max_entry_price=float(pick("MAX_ENTRY_PRICE", 0.45)),
        min_hours=float(pick("MIN_HOURS", 2.0)),
        max_hours=float(pick("MAX_HOURS", 72.0)),
        min_volume=float(pick("MIN_VOLUME", 500.0)),
        poll_interval_seconds=int(pick("POLL_INTERVAL_SECONDS", 3600)),
        monitor_interval_seconds=int(pick("MONITOR_INTERVAL_SECONDS", 600)),
        stale_order_seconds=int(pick("STALE_ORDER_SECONDS", 300)),
        weather_horizon_days=int(pick("WEATHER_HORIZON_DAYS", 4)),
        starting_balance=float(pick("STARTING_BALANCE", 10000.0)),
        kelly_fraction=float(pick("KELLY_FRACTION", 0.25)),
        calibration_min=int(pick("CALIBRATION_MIN", 30)),
        vc_key=str(pick("VC_KEY", "")),
        alert_webhook_url=str(pick("ALERT_WEBHOOK_URL", "")),
        database_path=str(pick("DATABASE_PATH", "data/skymarket.db")),
        log_level=str(pick("LOG_LEVEL", "INFO")).upper(),
    )
    config.validate()
    return config
