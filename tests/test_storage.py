from pathlib import Path

from skymarket.storage import Storage


def test_sqlite_round_trip(tmp_path: Path) -> None:
    storage = Storage(str(tmp_path / "bot.db"))
    storage.upsert_market_mapping(
        {
            "market_key": "nyc:2026-04-11:m1",
            "city": "nyc",
            "contract_date": "2026-04-11",
            "event_id": "e1",
            "market_id": "m1",
            "token_id": "t1",
            "outcome_side": "YES",
            "question": "Q",
            "bucket_low": 10.0,
            "bucket_high": 11.0,
            "best_bid": 0.2,
            "best_ask": 0.22,
            "spread": 0.02,
            "volume": 1000.0,
            "close_time": "2026-04-11T20:00:00Z",
            "resolution_time": "2026-04-11T20:00:00Z",
            "is_open": True,
            "is_tradable": True,
            "raw_market_json": "{}",
        }
    )
    storage.record_signal(
        "sig1",
        {
            "market_key": "nyc:2026-04-11:m1",
            "city": "nyc",
            "contract_date": "2026-04-11",
            "market_id": "m1",
            "token_id": "t1",
            "price": 0.22,
            "spread": 0.02,
            "edge": 0.15,
            "probability": 0.6,
            "size_usd": 10.0,
        },
        "ready",
    )
    storage.record_order(
        {
            "client_order_id": "o1",
            "broker_order_id": "o1",
            "market_key": "nyc:2026-04-11:m1",
            "market_id": "m1",
            "token_id": "t1",
            "side": "BUY",
            "price": 0.22,
            "size": 10.0,
            "status": "open",
            "signal_key": "sig1",
        }
    )
    storage.upsert_position(
        {
            "position_key": "nyc:2026-04-11:m1",
            "market_key": "nyc:2026-04-11:m1",
            "market_id": "m1",
            "token_id": "t1",
            "side": "BUY",
            "size": 10.0,
            "avg_price": 0.22,
            "status": "open",
        }
    )
    assert len(storage.list_market_mappings()) == 1
    assert len(storage.open_orders()) == 1
    assert len(storage.open_positions()) == 1
    storage.close()

