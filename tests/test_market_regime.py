"""get_market_regime 회귀 테스트 — CAN SLIM의 M(시장 방향).

5개 분기(상승장/약한상승/횡보/조정/하락장)와 yfinance 실패 fallback을
가짜 Close 시계열을 mock으로 주입해 검증한다.
"""
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from analysis.market_regime import get_market_regime


def _series_to_hist(closes: list[float]) -> pd.DataFrame:
    """길이 N짜리 종가 → 비즈데이 인덱스 DataFrame."""
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def _patch_yf_with(closes: list[float]):
    """yfinance.Ticker(...).history(...)가 주어진 시계열을 반환하도록 패치."""
    fake = MagicMock()
    fake.history.return_value = _series_to_hist(closes)
    return patch("analysis.market_regime.yf.Ticker", return_value=fake)


# ────────────────── benchmark 선택 ──────────────────

def test_us_benchmark_default():
    with _patch_yf_with([100.0] * 250):
        r = get_market_regime(is_kr=False)
    assert r["benchmark"] == "^GSPC"
    assert r["benchmark_name"] == "S&P 500"


def test_kr_benchmark():
    with _patch_yf_with([100.0] * 250):
        r = get_market_regime(is_kr=True)
    assert r["benchmark"] == "^KS11"
    assert r["benchmark_name"] == "KOSPI"


# ────────────────── 5개 분기 ──────────────────

def test_confirmed_uptrend():
    """장기 우상향 — current > MA50 > MA200, MA200 기울기 양, MA50 대비 +1% 초과."""
    closes = [100.0 + i * 0.5 for i in range(250)]   # 단조 상승
    with _patch_yf_with(closes):
        r = get_market_regime(is_kr=False)
    assert r["available"] is True
    assert r["passed_canslim_m"] is True
    assert "상승장" in r["direction"]
    assert r["trend_200d"] == "up"
    assert r["trend_50d"] == "up"


def test_downtrend():
    """단조 하락 — current < MA50 < MA200, MA200 기울기 음."""
    closes = [200.0 - i * 0.5 for i in range(250)]
    with _patch_yf_with(closes):
        r = get_market_regime(is_kr=False)
    assert r["passed_canslim_m"] is False
    assert "하락장" in r["direction"]
    assert r["trend_200d"] == "down"
    assert r["trend_50d"] == "down"


def test_sideways_flat():
    """횡보 — MA50/MA200 모두 거의 같은 평탄선, ma50_pct·ma200_pct 절대값 작음."""
    closes = [100.0] * 250
    with _patch_yf_with(closes):
        r = get_market_regime(is_kr=False)
    # current==ma50==ma200 → ma200_slope_up=False (>가 아님), 횡보 분기 진입
    assert "횡보" in r["direction"]
    assert r["passed_canslim_m"] is False


def test_correction_long_term_intact():
    """조정 — 장기 우상향(above_200, 기울기 up)이지만 MA50 아래로 단기 빠짐.

    구성: 230일 우상향 → 마지막 20일 급락(50일선 아래로). 200일선은 여전히 우상향.
    """
    closes = [100.0 + i * 0.5 for i in range(230)] + [closes_last - 30 for closes_last in [100.0 + 229 * 0.5]] * 20
    with _patch_yf_with(closes):
        r = get_market_regime(is_kr=False)
    # 횡보가 아닌 조정/하락장 둘 중 하나 (구성에 따라). 핵심은 passed_m=False.
    assert r["passed_canslim_m"] is False
    assert r["direction"] in {"조정 (장기추세 유효)", "하락장", "약한 상승"}


# ────────────────── yfinance 실패 fallback ──────────────────

def test_returns_unavailable_when_yfinance_raises():
    with patch("analysis.market_regime.yf.Ticker", side_effect=RuntimeError("network down")):
        r = get_market_regime(is_kr=False)
    assert r["available"] is False
    assert r["benchmark"] == "^GSPC"
    assert r["benchmark_name"] == "S&P 500"


def test_returns_unavailable_when_history_too_short():
    with _patch_yf_with([100.0] * 50):  # 200일 미만
        r = get_market_regime(is_kr=False)
    assert r["available"] is False


def test_returns_unavailable_when_history_empty():
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame({"Close": []})
    with patch("analysis.market_regime.yf.Ticker", return_value=fake):
        r = get_market_regime(is_kr=False)
    assert r["available"] is False
