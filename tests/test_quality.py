"""evaluate_earnings_quality 회귀 테스트.

stock 객체의 income_stmt/balance_sheet/cashflow는 yfinance가 주는 pandas DataFrame.
mock으로 최소 시나리오만 주입해 5가지 평가 분기(FCF/NI·발생액·매출채권·재고·적자) 검증.
"""
from unittest.mock import MagicMock

import pandas as pd

from analysis.quality import evaluate_earnings_quality


def _stock_with(inc: dict, bs: dict, cf: dict | None = None):
    """기간 컬럼이 2개인 mock 재무제표를 가진 stock 객체."""
    inc_df = pd.DataFrame(inc, index=list(inc.keys())[:0]) if False else pd.DataFrame(inc)
    bs_df = pd.DataFrame(bs)
    cf_df = pd.DataFrame(cf) if cf is not None else pd.DataFrame()
    s = MagicMock()
    s.income_stmt = inc_df
    s.balance_sheet = bs_df
    s.cashflow = cf_df
    return s


def _two_year(latest: dict, prev: dict) -> dict:
    """{'Net Income': [latest_val, prev_val], ...} 형태로 2기간 DataFrame 만들기 위한 입력."""
    out = {}
    for k in set(latest.keys()) | set(prev.keys()):
        out[k] = [latest.get(k), prev.get(k)]
    return out


def test_returns_unavailable_when_income_stmt_empty():
    s = MagicMock()
    s.income_stmt = pd.DataFrame()
    s.balance_sheet = pd.DataFrame({"Total Assets": [1000]})
    s.cashflow = pd.DataFrame()
    res = evaluate_earnings_quality(s, info={})
    assert res == {"available": False}


def test_returns_unavailable_when_stock_raises():
    s = MagicMock()
    type(s).income_stmt = property(lambda self: (_ for _ in ()).throw(RuntimeError("API down")))
    res = evaluate_earnings_quality(s, info={})
    assert res == {"available": False}


def test_strong_fcf_to_ni_ratio_passes():
    """FCF >= NI → 100점 strength."""
    inc = pd.DataFrame({0: [100], 1: [80]}, index=["Net Income"])
    bs = pd.DataFrame({0: [1000], 1: [900]}, index=["Total Assets"])
    cf = pd.DataFrame({0: [120]}, index=["Operating Cash Flow"])
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 120})
    assert res["available"] is True
    assert res["fcf_ni_ratio"] >= 1.0
    assert any("FCF > 순이익" in s for s in res["strengths"])
    assert res["quality_score"] >= 70


def test_weak_fcf_flags():
    """FCF/NI < 0.4 → 큰 flag."""
    inc = pd.DataFrame({0: [100], 1: [80]}, index=["Net Income"])
    bs = pd.DataFrame({0: [1000], 1: [900]}, index=["Total Assets"])
    cf = pd.DataFrame({0: [10]}, index=["Operating Cash Flow"])
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 10})
    assert any("매우 낮음" in f for f in res["flags"])


def test_high_accruals_flag():
    """(NI - OCF)/Assets > 0.10 → 발생액 높음 flag."""
    inc = pd.DataFrame({0: [200]}, index=["Net Income"])
    bs = pd.DataFrame({0: [1000]}, index=["Total Assets"])
    cf = pd.DataFrame({0: [50]}, index=["Operating Cash Flow"])  # accruals = (200-50)/1000 = 0.15
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 50})
    assert res["accruals_ratio"] > 0.10
    assert any("발생액 비율 높음" in f for f in res["flags"])


def test_ar_growing_faster_than_revenue_flags():
    """매출채권이 매출보다 15%p+ 빠르게 증가 → 매출 푸싱 의심 flag."""
    inc = pd.DataFrame({
        0: [100, 1000],   # latest: NI=100, Revenue=1000
        1: [80, 950],     # prev:   NI=80,  Revenue=950 (5% growth)
    }, index=["Net Income", "Total Revenue"])
    bs = pd.DataFrame({
        0: [1000, 500],   # latest: Assets=1000, AR=500
        1: [900, 250],    # prev:   Assets=900,  AR=250 (100% AR growth → 95%p faster)
    }, index=["Total Assets", "Accounts Receivable"])
    cf = pd.DataFrame({0: [80]}, index=["Operating Cash Flow"])
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 80})
    assert res["ar_growth_vs_rev"] > 0.15
    assert any("매출채권" in f and "푸싱" in f for f in res["flags"])


def test_inventory_growing_faster_flags():
    """재고가 매출보다 20%p+ 빠르게 증가 → 악성재고 우려."""
    inc = pd.DataFrame({
        0: [100, 1000],
        1: [80, 950],
    }, index=["Net Income", "Total Revenue"])
    bs = pd.DataFrame({
        0: [1000, 500],   # Inventory latest=500
        1: [900, 200],    # Inventory prev=200 (150% growth)
    }, index=["Total Assets", "Inventory"])
    cf = pd.DataFrame({0: [80]}, index=["Operating Cash Flow"])
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 80})
    assert res["inventory_growth_vs_rev"] > 0.20
    assert any("재고" in f and ("악성" in f or "판매둔화" in f) for f in res["flags"])


def test_negative_net_income_adds_severe_flag():
    inc = pd.DataFrame({0: [-50]}, index=["Net Income"])
    bs = pd.DataFrame({0: [1000]}, index=["Total Assets"])
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=pd.DataFrame())
    res = evaluate_earnings_quality(s, info={})
    assert any("적자" in f for f in res["flags"])
    assert res["quality_score"] is not None and res["quality_score"] <= 30


def test_quality_score_bounds():
    """모든 분기 통과 시 quality_score는 0~100 범위 유지."""
    inc = pd.DataFrame({
        0: [100, 1000],
        1: [80, 950],
    }, index=["Net Income", "Total Revenue"])
    bs = pd.DataFrame({
        0: [1000, 100, 50],
        1: [900, 95, 48],
    }, index=["Total Assets", "Accounts Receivable", "Inventory"])
    cf = pd.DataFrame({0: [110]}, index=["Operating Cash Flow"])  # 발생액 낮음
    s = MagicMock(income_stmt=inc, balance_sheet=bs, cashflow=cf)
    res = evaluate_earnings_quality(s, info={"freeCashflow": 120})
    assert 0 <= res["quality_score"] <= 100
