from mini import fmt, parse


def test_roundtrip():
    assert fmt(parse("1h30m")) == "1h30m"
