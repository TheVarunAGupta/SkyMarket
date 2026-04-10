from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_mappings (
                market_key TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                contract_date TEXT NOT NULL,
                event_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                outcome_side TEXT NOT NULL,
                question TEXT NOT NULL,
                bucket_low REAL NOT NULL,
                bucket_high REAL NOT NULL,
                best_bid REAL NOT NULL,
                best_ask REAL NOT NULL,
                spread REAL NOT NULL,
                volume REAL NOT NULL,
                close_time TEXT,
                resolution_time TEXT,
                is_open INTEGER NOT NULL,
                is_tradable INTEGER NOT NULL,
                raw_market_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_key TEXT PRIMARY KEY,
                market_key TEXT NOT NULL,
                city TEXT NOT NULL,
                contract_date TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                price REAL NOT NULL,
                spread REAL NOT NULL,
                edge REAL NOT NULL,
                probability REAL NOT NULL,
                size_usd REAL NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                broker_order_id TEXT,
                market_key TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                status TEXT NOT NULL,
                signal_key TEXT,
                placed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fills (
                broker_fill_id TEXT PRIMARY KEY,
                broker_order_id TEXT,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                created_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                position_key TEXT PRIMARY KEY,
                market_key TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                avg_price REAL NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                day TEXT PRIMARY KEY,
                realized_pnl REAL NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reconciliation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_market_mapping(self, mapping: dict[str, Any]) -> None:
        payload = dict(mapping)
        payload["updated_at"] = utc_now()
        payload["is_open"] = int(bool(payload["is_open"]))
        payload["is_tradable"] = int(bool(payload["is_tradable"]))
        columns = ",".join(payload.keys())
        placeholders = ",".join("?" for _ in payload)
        updates = ",".join(f"{key}=excluded.{key}" for key in payload if key != "market_key")
        self.conn.execute(
            f"INSERT INTO market_mappings ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(market_key) DO UPDATE SET {updates}",
            tuple(payload.values()),
        )
        self.conn.commit()

    def list_market_mappings(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM market_mappings").fetchall()
        return [dict(row) for row in rows]

    def record_signal(self, signal_key: str, payload: dict[str, Any], status: str, reason: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO signals
            (signal_key, market_key, city, contract_date, market_id, token_id, price, spread, edge, probability, size_usd, status, reason, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_key,
                payload["market_key"],
                payload["city"],
                payload["contract_date"],
                payload["market_id"],
                payload["token_id"],
                payload["price"],
                payload["spread"],
                payload["edge"],
                payload["probability"],
                payload["size_usd"],
                status,
                reason,
                json.dumps(payload, ensure_ascii=True),
                utc_now(),
            ),
        )
        self.conn.commit()

    def record_order(self, payload: dict[str, Any]) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (client_order_id, broker_order_id, market_key, market_id, token_id, side, price, size, status, signal_key, placed_at, updated_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["client_order_id"],
                payload.get("broker_order_id"),
                payload["market_key"],
                payload["market_id"],
                payload["token_id"],
                payload["side"],
                payload["price"],
                payload["size"],
                payload["status"],
                payload.get("signal_key"),
                payload.get("placed_at", now),
                now,
                json.dumps(payload, ensure_ascii=True),
            ),
        )
        self.conn.commit()

    def update_order_status(self, client_order_id: str, status: str, raw_payload: dict[str, Any] | None = None) -> None:
        row = self.conn.execute("SELECT raw_json FROM orders WHERE client_order_id = ?", (client_order_id,)).fetchone()
        payload = json.loads(row["raw_json"]) if row else {}
        if raw_payload:
            payload.update(raw_payload)
        self.conn.execute(
            "UPDATE orders SET status = ?, updated_at = ?, raw_json = ? WHERE client_order_id = ?",
            (status, utc_now(), json.dumps(payload, ensure_ascii=True), client_order_id),
        )
        self.conn.commit()

    def open_orders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status IN ('pending', 'open', 'unknown')"
        ).fetchall()
        return [dict(row) for row in rows]

    def record_fill(self, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO fills
            (broker_fill_id, broker_order_id, market_id, token_id, side, price, size, created_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["broker_fill_id"],
                payload.get("broker_order_id"),
                payload["market_id"],
                payload["token_id"],
                payload["side"],
                payload["price"],
                payload["size"],
                payload.get("created_at", utc_now()),
                json.dumps(payload, ensure_ascii=True),
            ),
        )
        self.conn.commit()

    def upsert_position(self, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO positions
            (position_key, market_key, market_id, token_id, side, size, avg_price, status, updated_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["position_key"],
                payload["market_key"],
                payload["market_id"],
                payload["token_id"],
                payload["side"],
                payload["size"],
                payload["avg_price"],
                payload["status"],
                utc_now(),
                json.dumps(payload, ensure_ascii=True),
            ),
        )
        self.conn.commit()

    def open_positions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM positions WHERE status IN ('open', 'unknown')"
        ).fetchall()
        return [dict(row) for row in rows]

    def market_exposure(self, market_key: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS exposure FROM positions WHERE market_key = ? AND status IN ('open', 'unknown')",
            (market_key,),
        ).fetchone()
        return float(row["exposure"]) if row else 0.0

    def total_exposure(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS exposure FROM positions WHERE status IN ('open', 'unknown')"
        ).fetchone()
        return float(row["exposure"]) if row else 0.0

    def realized_pnl_today(self) -> float:
        day = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute("SELECT realized_pnl FROM daily_pnl WHERE day = ?", (day,)).fetchone()
        return float(row["realized_pnl"]) if row else 0.0

    def set_realized_pnl_today(self, amount: float) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO daily_pnl (day, realized_pnl, updated_at) VALUES (?, ?, ?)",
            (day, amount, utc_now()),
        )
        self.conn.commit()

    def add_reconciliation_event(self, event_type: str, details: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO reconciliation_events (event_type, details, created_at) VALUES (?, ?, ?)",
            (event_type, json.dumps(details, ensure_ascii=True), utc_now()),
        )
        self.conn.commit()

