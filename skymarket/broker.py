from __future__ import annotations

import requests
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from eth_account import Account

from .config import Config


@dataclass(frozen=True)
class OrderRequest:
    market_key: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    signal_key: str


class Broker(ABC):
    @abstractmethod
    def get_balance(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, request: OrderRequest) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel_all_for_market(self, market_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_fills(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_order_status(self, order_id: str) -> dict[str, Any]:
        raise NotImplementedError


class PaperBroker(Broker):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.balance = config.starting_balance
        self.orders: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, dict[str, Any]] = {}

    def get_balance(self) -> float:
        return round(self.balance, 2)

    def get_open_orders(self) -> list[dict[str, Any]]:
        return [order for order in self.orders.values() if order["status"] == "open"]

    def get_positions(self) -> list[dict[str, Any]]:
        return [position for position in self.positions.values() if position["status"] == "open"]

    def place_order(self, request: OrderRequest) -> dict[str, Any]:
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        order = {
            "id": order_id,
            "client_order_id": order_id,
            "market_key": request.market_key,
            "market_id": request.market_id,
            "asset_id": request.token_id,
            "price": request.price,
            "original_size": request.size,
            "size_matched": request.size,
            "side": request.side,
            "status": "filled",
            "signal_key": request.signal_key,
        }
        self.orders[order_id] = order
        self.balance = max(0.0, self.balance - request.size * request.price)
        self.positions[request.market_key] = {
            "id": request.market_key,
            "market_key": request.market_key,
            "market_id": request.market_id,
            "asset_id": request.token_id,
            "side": request.side,
            "size": request.size,
            "avg_price": request.price,
            "status": "open",
        }
        return order

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self.orders.get(order_id, {"id": order_id, "status": "unknown"})
        order["status"] = "cancelled"
        self.orders[order_id] = order
        return order

    def cancel_all_for_market(self, market_id: str) -> list[dict[str, Any]]:
        cancelled = []
        for order in self.orders.values():
            if order["market_id"] == market_id and order["status"] == "open":
                order["status"] = "cancelled"
                cancelled.append(order)
        return cancelled

    def fetch_fills(self) -> list[dict[str, Any]]:
        fills = []
        for order in self.orders.values():
            if order["status"] == "filled":
                fills.append(
                    {
                        "id": f"fill-{order['id']}",
                        "order_id": order["id"],
                        "market_id": order["market_id"],
                        "asset_id": order["asset_id"],
                        "price": order["price"],
                        "size": order["size_matched"],
                        "side": order["side"],
                    }
                )
        return fills

    def fetch_order_status(self, order_id: str) -> dict[str, Any]:
        return self.orders.get(order_id, {"id": order_id, "status": "unknown"})


class PolymarketBroker(Broker):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = self._build_client()
        self.user_address = self.config.funder or Account.from_key(self.config.private_key).address

    def _build_client(self) -> Any:
        from py_clob_client.client import ClobClient

        kwargs: dict[str, Any] = {
            "key": self.config.private_key,
            "chain_id": self.config.chain_id,
            "signature_type": self.config.signature_type,
        }
        if self.config.funder:
            kwargs["funder"] = self.config.funder
        client = ClobClient(self.config.clob_host, **kwargs)
        client.set_api_creds(client.create_or_derive_api_creds())
        return client

    def get_balance(self) -> float:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        payload = self.client.get_balance_allowance(
            BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=self.config.signature_type,
            )
        )
        balance = payload.get("balance") or payload.get("available") or payload.get("allowance") or 0
        return float(balance) / 1_000_000

    def get_open_orders(self) -> list[dict[str, Any]]:
        from py_clob_client.clob_types import OpenOrderParams

        return list(self.client.get_orders(OpenOrderParams()))

    def get_positions(self) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.config.data_api_host}/positions",
            params={"user": self.user_address, "sizeThreshold": 1},
            timeout=(5, 10),
        )
        response.raise_for_status()
        return response.json()

    def place_order(self, request: OrderRequest) -> dict[str, Any]:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        if request.side.upper() != "BUY":
            raise ValueError("This v1 live bot only submits BUY orders")
        order = OrderArgs(token_id=request.token_id, price=request.price, size=request.size, side=BUY)
        signed = self.client.create_order(order)
        response = self.client.post_order(signed, OrderType.GTC)
        response["client_order_id"] = response.get("id") or response.get("orderID") or str(uuid.uuid4())
        return response

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return dict(self.client.cancel(order_id))

    def cancel_all_for_market(self, market_id: str) -> list[dict[str, Any]]:
        cancelled = []
        for order in self.get_open_orders():
            if str(order.get("market")) == market_id or str(order.get("market_id")) == market_id:
                cancelled.append(dict(self.client.cancel(order["id"])))
        return cancelled

    def fetch_fills(self) -> list[dict[str, Any]]:
        return list(self.client.get_trades())

    def fetch_order_status(self, order_id: str) -> dict[str, Any]:
        return dict(self.client.get_order(order_id))


def build_broker(config: Config) -> Broker:
    if config.mode == "live" and not config.dry_run:
        return PolymarketBroker(config)
    return PaperBroker(config)
