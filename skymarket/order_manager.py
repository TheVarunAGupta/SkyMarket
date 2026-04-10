from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .broker import Broker, OrderRequest
from .config import Config
from .storage import Storage
from .strategy import TradeIdea


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


class OrderManager:
    def __init__(self, config: Config, storage: Storage, broker: Broker, logger: Any) -> None:
        self.config = config
        self.storage = storage
        self.broker = broker
        self.logger = logger

    def reconcile(self) -> dict[str, int]:
        local_orders = {row["broker_order_id"] or row["client_order_id"]: row for row in self.storage.open_orders()}
        broker_orders = self.broker.get_open_orders()
        broker_positions = self.broker.get_positions()
        broker_order_ids = set()

        for order in broker_orders:
            broker_id = str(order.get("id") or order.get("orderID") or "")
            if not broker_id:
                continue
            broker_order_ids.add(broker_id)
            self.storage.record_order(
                {
                    "client_order_id": broker_id,
                    "broker_order_id": broker_id,
                    "market_key": str(order.get("market_key") or order.get("market") or order.get("market_id") or ""),
                    "market_id": str(order.get("market") or order.get("market_id") or ""),
                    "token_id": str(order.get("asset_id") or order.get("token_id") or ""),
                    "side": str(order.get("side", "BUY")),
                    "price": float(order.get("price", 0.0)),
                    "size": float(order.get("original_size") or order.get("size") or 0.0),
                    "status": str(order.get("status", "open")).lower(),
                    "signal_key": order.get("signal_key"),
                    "placed_at": order.get("created_at") or datetime.now(timezone.utc).isoformat(),
                }
            )

        for broker_id, local in local_orders.items():
            if broker_id not in broker_order_ids:
                self.storage.update_order_status(local["client_order_id"], "unknown")
                self.storage.add_reconciliation_event(
                    "missing_local_order_on_broker",
                    {"client_order_id": local["client_order_id"], "market_key": local["market_key"]},
                )

        for position in broker_positions:
            market_key = str(position.get("market_key") or position.get("market") or position.get("market_id") or position.get("asset_id") or "")
            self.storage.upsert_position(
                {
                    "position_key": market_key,
                    "market_key": market_key,
                    "market_id": str(position.get("market") or position.get("market_id") or ""),
                    "token_id": str(position.get("asset_id") or position.get("token_id") or ""),
                    "side": str(position.get("side", "BUY")),
                    "size": float(position.get("size", 0.0)),
                    "avg_price": float(position.get("avg_price") or position.get("initialValue") or 0.0),
                    "status": "open",
                }
            )

        fills = self.broker.fetch_fills()
        for fill in fills:
            fill_id = str(fill.get("id") or fill.get("tradeID") or fill.get("transactionHash") or "")
            if not fill_id:
                continue
            self.storage.record_fill(
                {
                    "broker_fill_id": fill_id,
                    "broker_order_id": str(fill.get("order_id") or fill.get("orderID") or ""),
                    "market_id": str(fill.get("market_id") or fill.get("market") or ""),
                    "token_id": str(fill.get("asset_id") or fill.get("token_id") or ""),
                    "side": str(fill.get("side", "BUY")),
                    "price": float(fill.get("price", 0.0)),
                    "size": float(fill.get("size", 0.0)),
                    "created_at": fill.get("created_at") or datetime.now(timezone.utc).isoformat(),
                }
            )

        return {
            "broker_open_orders": len(broker_orders),
            "broker_positions": len(broker_positions),
            "fills_seen": len(fills),
        }

    def check_risk(self, idea: TradeIdea) -> RiskDecision:
        if self.config.kill_switch:
            return RiskDecision(False, "kill_switch_enabled")
        if self.config.mode == "live" and not self.config.live_trading_enabled:
            return RiskDecision(False, "live_trading_not_enabled")
        if self.config.allowed_cities and idea.city not in self.config.allowed_cities:
            return RiskDecision(False, "city_not_whitelisted")
        if idea.edge < self.config.min_edge:
            return RiskDecision(False, "edge_below_threshold")
        if idea.spread > self.config.max_spread:
            return RiskDecision(False, "spread_above_threshold")
        order_notional = round(idea.price * idea.shares, 2)
        if order_notional > self.config.max_order_size:
            return RiskDecision(False, "order_size_above_limit")
        if self.storage.market_exposure(idea.market_key) + order_notional > self.config.max_position_per_market:
            return RiskDecision(False, "market_exposure_above_limit")
        if self.storage.total_exposure() + order_notional > self.config.max_total_exposure:
            return RiskDecision(False, "total_exposure_above_limit")
        if abs(self.storage.realized_pnl_today()) >= self.config.max_daily_loss and self.storage.realized_pnl_today() < 0:
            return RiskDecision(False, "daily_loss_limit_reached")
        if self._has_duplicate_interest(idea.market_key):
            return RiskDecision(False, "duplicate_market_interest")
        return RiskDecision(True, "ok")

    def process_trade_ideas(self, ideas: list[TradeIdea]) -> list[dict[str, Any]]:
        submitted: list[dict[str, Any]] = []
        for idea in ideas:
            signal_payload = idea.as_dict()
            risk = self.check_risk(idea)
            if not risk.allowed:
                self.storage.record_signal(idea.signal_key, signal_payload, "blocked", risk.reason)
                self.logger.info({"event": "trade_blocked", "signal_key": idea.signal_key, "reason": risk.reason})
                continue

            self.storage.record_signal(idea.signal_key, signal_payload, "ready")
            order = self.broker.place_order(
                OrderRequest(
                    market_key=idea.market_key,
                    market_id=idea.market_id,
                    token_id=idea.token_id,
                    side="BUY",
                    price=idea.price,
                    size=idea.shares,
                    signal_key=idea.signal_key,
                )
            )
            broker_order_id = str(order.get("id") or order.get("orderID") or order.get("client_order_id"))
            status = str(order.get("status", "pending")).lower()
            order_payload = {
                "client_order_id": broker_order_id,
                "broker_order_id": broker_order_id,
                "market_key": idea.market_key,
                "market_id": idea.market_id,
                "token_id": idea.token_id,
                "side": "BUY",
                "price": idea.price,
                "size": idea.shares,
                "status": status,
                "signal_key": idea.signal_key,
                "placed_at": datetime.now(timezone.utc).isoformat(),
            }
            self.storage.record_order(order_payload)
            if status == "filled":
                self.storage.upsert_position(
                    {
                        "position_key": idea.market_key,
                        "market_key": idea.market_key,
                        "market_id": idea.market_id,
                        "token_id": idea.token_id,
                        "side": "BUY",
                        "size": round(idea.price * idea.shares, 2),
                        "avg_price": idea.price,
                        "status": "open",
                    }
                )
            self.logger.info({"event": "order_submitted", "signal_key": idea.signal_key, "broker_order_id": broker_order_id})
            submitted.append(order_payload)
        return submitted

    def refresh_orders(self) -> list[dict[str, Any]]:
        updated: list[dict[str, Any]] = []
        for order in self.storage.open_orders():
            status_payload = self.broker.fetch_order_status(order["broker_order_id"] or order["client_order_id"])
            status = str(status_payload.get("status", order["status"])).lower()
            self.storage.update_order_status(order["client_order_id"], status, status_payload)
            updated.append({"client_order_id": order["client_order_id"], "status": status})
        return updated

    def cancel_stale_orders(self) -> list[str]:
        cancelled: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.config.stale_order_seconds)
        for order in self.storage.open_orders():
            placed_at = _parse_ts(order["placed_at"])
            if placed_at and placed_at < cutoff:
                broker_order_id = order["broker_order_id"] or order["client_order_id"]
                self.broker.cancel_order(broker_order_id)
                self.storage.update_order_status(order["client_order_id"], "cancelled")
                cancelled.append(order["client_order_id"])
        return cancelled

    def _has_duplicate_interest(self, market_key: str) -> bool:
        open_orders = self.storage.open_orders()
        if any(order["market_key"] == market_key for order in open_orders):
            return True
        open_positions = self.storage.open_positions()
        return any(position["market_key"] == market_key for position in open_positions)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
