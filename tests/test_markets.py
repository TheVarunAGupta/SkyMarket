from skymarket.markets import map_event_to_markets


def test_map_event_to_tradable_yes_token() -> None:
    event = {
        "id": "evt1",
        "endDate": "2026-04-11T20:00:00Z",
        "markets": [
            {
                "id": "m1",
                "question": "Will the highest temperature in Chicago be between 46-47°F on April 11?",
                "clobTokenIds": '["yes-token","no-token"]',
                "outcomes": '["Yes","No"]',
                "bestBid": 0.31,
                "bestAsk": 0.33,
                "active": True,
                "closed": False,
                "volume": 1234,
            }
        ],
    }
    mappings = map_event_to_markets("chicago", "2026-04-11", event)
    assert len(mappings) == 1
    assert mappings[0].token_id == "yes-token"
    assert mappings[0].bucket_low == 46
    assert mappings[0].bucket_high == 47
    assert mappings[0].is_tradable is True

