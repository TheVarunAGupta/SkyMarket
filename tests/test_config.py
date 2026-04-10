import json
from pathlib import Path

import pytest

from skymarket.config import load_config


def test_loads_legacy_json_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"balance": 5000, "max_bet": 15, "min_ev": 0.2, "max_slippage": 0.01}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.starting_balance == 5000
    assert config.max_order_size == 15
    assert config.min_edge == 0.2
    assert config.max_spread == 0.01


def test_live_config_fails_fast_without_required_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    with pytest.raises(ValueError):
        load_config()

