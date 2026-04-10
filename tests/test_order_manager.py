import logging

from skymarket.broker import Broker
from skymarket.config import Config
from skymarket.order_manager import OrderManager
from skymarket.storage import Storage
from skymarket.strategy import TradeIdea


class StubBroker(Broker):
    def __init__(self) -> None:
        self.orders = []
        self.positions = []
        self.fills = []

    def get_balance(self) -> float:
        return 1000.0

    def get_open_orders(self):
        return self.orders

    def get_positions(self):
        return self.positions

    def place_order(self, request):
        return {"id": "broker-1", "status": "filled", "market": request.market_id}

    def cancel_order(self, order_id: str):
        return {"id": order_id, "status": "cancelled"}

    def cancel_all_for_market(self, market_id: str):
        return []

    def fetch_fills(self):
        return self.fills

    def fetch_order_status(self, order_id: str):
        return {"id": order_id, "status": "filled"}


def make_idea() -> TradeIdea:
    return TradeIdea(
        signal_key="sig-1",
        market_key="chi:2026-04-11:m1",
        city="chicago",
        contract_date="2026-04-11",
        market_id="m1",
        token_id="t1",
        question="Q",
        price=0.3,
        bid=0.28,
        spread=0.02,
        volume=1000.0,
        bucket_low=46.0,
        bucket_high=47.0,
        forecast_temp=46.0,
        forecast_source="ecmwf",
        probability=0.6,
        edge=0.15,
        kelly_fraction=0.1,
        size_usd=10.0,
        shares=10.0,
        hours_left=12.0,
    )


def test_risk_blocks_when_kill_switch_enabled(tmp_path) -> None:
    config = Config(kill_switch=True)
    storage = Storage(str(tmp_path / "bot.db"))
    manager = OrderManager(config, storage, StubBroker(), logging.getLogger("test"))
    decision = manager.check_risk(make_idea())
    assert decision.allowed is False
    assert decision.reason == "kill_switch_enabled"


def test_reconciliation_marks_missing_local_orders_unknown(tmp_path) -> None:
    config = Config(kill_switch=False, live_trading_enabled=True)
    storage = Storage(str(tmp_path / "bot.db"))
    storage.record_order(
        {
            "client_order_id": "o-local",
            "broker_order_id": "o-local",
            "market_key": "chi:2026-04-11:m1",
            "market_id": "m1",
            "token_id": "t1",
            "side": "BUY",
            "price": 0.3,
            "size": 10,
            "status": "open",
            "signal_key": "sig-1",
        }
    )
    manager = OrderManager(config, storage, StubBroker(), logging.getLogger("test"))
    manager.reconcile()
    assert storage.open_orders()[0]["status"] == "unknown"


def test_duplicate_signal_is_blocked_after_position_exists(tmp_path) -> None:
    config = Config(kill_switch=False, live_trading_enabled=True)
    storage = Storage(str(tmp_path / "bot.db"))
    storage.upsert_position(
        {
            "position_key": "chi:2026-04-11:m1",
            "market_key": "chi:2026-04-11:m1",
            "market_id": "m1",
            "token_id": "t1",
            "side": "BUY",
            "size": 10,
            "avg_price": 0.3,
            "status": "open",
        }
    )
    manager = OrderManager(config, storage, StubBroker(), logging.getLogger("test"))
    decision = manager.check_risk(make_idea())
    assert decision.allowed is False
    assert decision.reason == "duplicate_market_interest"
