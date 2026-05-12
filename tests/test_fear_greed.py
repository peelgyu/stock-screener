"""공포탐욕지수 회귀 테스트.

배경: 2026-05-12 daily_briefing.py:179가 존재하지 않는
calculate_fear_greed를 import하다 silent ImportError로 매일 null 저장 중이었다.
이 테스트는 (1) 함수 import 가능성, (2) wrapper의 level/available 매핑,
(3) daily_briefing 호출 경로가 dict를 받는지 — 셋을 회귀 방지로 잠근다.
"""
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


# ────────────────── 1) import 가능성 (라이브 버그 재현 방지) ──────────────────

def test_calculate_fear_greed_is_importable():
    """daily_briefing.py:179가 의존하는 import 경로가 살아있는가."""
    from analysis.fear_greed import calculate_fear_greed
    assert callable(calculate_fear_greed)


# ────────────────── 2) score → level 매핑 ──────────────────

@pytest.mark.parametrize("score,expected_level", [
    (90, "extreme_greed"),
    (75, "extreme_greed"),
    (60, "greed"),
    (55, "greed"),
    (50, "neutral"),
    (45, "neutral"),
    (30, "fear"),
    (25, "fear"),
    (10, "extreme_fear"),
    (0,  "extreme_fear"),
    (None, None),
])
def test_score_to_level_mapping(score, expected_level):
    from analysis.fear_greed import _score_to_level
    assert _score_to_level(score) == expected_level


# ────────────────── 3) wrapper 정상 동작 (mock) ──────────────────

def _fake_hist(rows: int = 250) -> pd.DataFrame:
    """evaluate_fear_greed가 RSI/이평/변동성을 계산할 수 있는 최소 시계열."""
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    base = 4500.0
    closes = [base + i * 0.5 for i in range(rows)]
    return pd.DataFrame({
        "Close": closes,
        "Volume": [1_000_000] * rows,
    }, index=idx)


def test_calculate_fear_greed_returns_full_dict():
    """yfinance mock 시 wrapper가 score/label/level/available을 모두 채워야."""
    from analysis import fear_greed as fg

    fake_ticker = MagicMock()
    fake_ticker.info = {
        "currentPrice": 4600,
        "fiftyTwoWeekHigh": 4800,
        "fiftyTwoWeekLow": 3900,
    }
    fake_ticker.history.return_value = _fake_hist()

    with patch.object(fg, "yf", create=True) if False else patch("yfinance.Ticker", return_value=fake_ticker):
        result = fg.calculate_fear_greed("^GSPC")

    assert set(["available", "score", "label", "level", "indicators"]).issubset(result.keys())
    assert result["available"] is True
    assert isinstance(result["score"], int)
    assert result["level"] in {"extreme_fear", "fear", "neutral", "greed", "extreme_greed"}
    assert isinstance(result["indicators"], list)
    assert len(result["indicators"]) >= 3


def test_calculate_fear_greed_handles_yfinance_failure():
    """yfinance 예외 시 available=False로 graceful return."""
    from analysis import fear_greed as fg

    with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
        result = fg.calculate_fear_greed("^GSPC")

    assert result == {
        "available": False,
        "score": None,
        "label": None,
        "level": None,
        "indicators": [],
    }


# ────────────────── 4) daily_briefing 호출 경로 ──────────────────

def test_daily_briefing_fetch_fear_greed_returns_dict_when_available():
    """_fetch_fear_greed가 score 있는 dict를 받으면 정상 dict 반환해야."""
    from data import daily_briefing

    fake_result = {
        "available": True,
        "score": 60,
        "label": "탐욕",
        "level": "greed",
        "indicators": [],
    }
    with patch("analysis.fear_greed.calculate_fear_greed", return_value=fake_result):
        out = daily_briefing._fetch_fear_greed()

    assert out == {"score": 60, "label": "탐욕", "level": "greed"}


def test_daily_briefing_fetch_fear_greed_returns_none_when_unavailable():
    """available=False면 None — 기존 caller 계약 유지."""
    from data import daily_briefing

    with patch("analysis.fear_greed.calculate_fear_greed",
               return_value={"available": False, "score": None, "label": None, "level": None, "indicators": []}):
        out = daily_briefing._fetch_fear_greed()

    assert out is None
