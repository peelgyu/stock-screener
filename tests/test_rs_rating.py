"""calculate_rs_rating 회귀 테스트.

벤치마크 자동 선택(US ^GSPC vs KR ^KS11), 기간별 RS 점수, 가중 합성, 라벨링.
yfinance.Ticker는 mock으로 가짜 시계열 주입.
"""
from unittest.mock import patch, MagicMock

import pandas as pd

from analysis.rs_rating import calculate_rs_rating, _benchmark_for, _rs_score


def _hist_with_close(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def _patch_yf(stock_closes: list[float], bench_closes: list[float]):
    """yf.Ticker(symbol).history(...) → 종목·벤치마크별 다른 시계열 반환."""
    def make_ticker(symbol):
        m = MagicMock()
        if symbol in ("^GSPC", "^KS11"):
            m.history.return_value = _hist_with_close(bench_closes)
        else:
            m.history.return_value = _hist_with_close(stock_closes)
        return m
    return patch("analysis.rs_rating.yf.Ticker", side_effect=make_ticker)


# ────────────────── 벤치마크 자동 선택 ──────────────────

def test_benchmark_us_default():
    assert _benchmark_for("AAPL") == "^GSPC"


def test_benchmark_kospi_for_ks_suffix():
    assert _benchmark_for("005930.KS") == "^KS11"


def test_benchmark_kospi_for_kq_suffix():
    assert _benchmark_for("066970.KQ") == "^KS11"


def test_benchmark_handles_none_input():
    assert _benchmark_for(None) == "^GSPC"
    assert _benchmark_for("") == "^GSPC"


# ────────────────── RS score 공식 ──────────────────

def test_rs_score_market_match_returns_50():
    """주식 수익률 = 벤치마크 → 50점."""
    assert _rs_score(0.10, 0.10) == 50


def test_rs_score_outperform_above_50():
    """주식이 10%p 상회 → 50 + 0.10*500 = 100 → clamped 100."""
    assert _rs_score(0.15, 0.05) == 100


def test_rs_score_underperform_below_50():
    """주식이 -10%p 하회 → 50 - 50 = 0."""
    assert _rs_score(-0.05, 0.05) == 0


def test_rs_score_clamped_to_100():
    """극단 outperform → 상한 100."""
    assert _rs_score(2.0, 0.0) == 100


def test_rs_score_clamped_to_0():
    """극단 underperform → 하한 0."""
    assert _rs_score(-2.0, 0.0) == 0


def test_rs_score_returns_none_on_missing_input():
    assert _rs_score(None, 0.10) is None
    assert _rs_score(0.10, None) is None


# ────────────────── calculate_rs_rating 통합 ──────────────────

def test_returns_unavailable_when_history_empty():
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame({"Close": []})
    with patch("analysis.rs_rating.yf.Ticker", return_value=fake):
        with patch("analysis.rs_rating.cache", None):
            res = calculate_rs_rating("AAPL")
    assert res["available"] is False
    assert res["benchmark"] == "^GSPC"


def test_outperformer_gets_high_composite():
    """주식 단조 +50%, 벤치마크 +5% → composite >= 80, 라벨 '선도주'."""
    stock = [100.0 + i * 0.20 for i in range(260)]    # ~+50%/yr
    bench = [100.0 + i * 0.02 for i in range(260)]    # ~+5%/yr
    with _patch_yf(stock, bench):
        with patch("analysis.rs_rating.cache", None):
            res = calculate_rs_rating("AAPL")
    assert res["available"] is True
    assert res["rs_composite"] >= 80
    assert "선도주" in res["label"]
    assert res["passed_oneil"] is True


def test_underperformer_gets_low_composite():
    """주식 단조 -50%, 벤치마크 +5% → composite <= 40."""
    stock = [200.0 - i * 0.40 for i in range(260)]
    bench = [100.0 + i * 0.02 for i in range(260)]
    with _patch_yf(stock, bench):
        with patch("analysis.rs_rating.cache", None):
            res = calculate_rs_rating("AAPL")
    assert res["rs_composite"] <= 40
    assert "부진" in res["label"]
    assert res["passed_oneil"] is False


def test_market_match_gets_around_50():
    """주식과 벤치마크 동일 시계열 → composite ≈ 50."""
    series = [100.0 + i * 0.10 for i in range(260)]
    with _patch_yf(series, series):
        with patch("analysis.rs_rating.cache", None):
            res = calculate_rs_rating("AAPL")
    assert 40 <= res["rs_composite"] <= 60
