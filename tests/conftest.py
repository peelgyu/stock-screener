"""pytest 공통 fixture — 평가자 함수 검증용 가짜 데이터.

5인 평가자(워렌 버핏·그레이엄·린치·오닐·피셔)는 외부 API 호출 없이 info dict 입력만 받아
규칙 기반 채점 결과를 반환하는 순수 함수다. 테스트는 그 회귀를 막는 안전망 역할.
"""
import os
import sys

# stockinto 루트를 sys.path에 추가 (tests/ 안에서 from analysis import ... 가능하게)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest


# Flask app import는 외부 의존성 (yfinance, dart_client) 트리거하므로 보호
@pytest.fixture(scope="session")
def app_module():
    """app.py 모듈 한 번만 로드 — Flask 앱 부수효과 1회만 발생."""
    import app
    return app


@pytest.fixture
def sector_thresholds_tech():
    """Technology 섹터 기준값 (테스트용 명시 고정값)."""
    return {
        "per_max": 35, "pbr_max": 8.0, "de_max": 100,
        "om_min": 0.18, "gm_min": 0.5, "pm_min": 0.12,
        "roe_min": 0.15, "rev_growth_min": 0.10, "median_pe": 32,
        "sector": "Technology",
    }


@pytest.fixture
def info_strong_tech():
    """강한 Tech 종목 (AAPL 스타일) — 대부분 기준 통과해야 함."""
    return {
        "returnOnEquity": 0.30,           # 30% — 매우 높음
        "debtToEquity": 60,                # 보수적
        "operatingMargins": 0.30,
        "grossMargins": 0.45,
        "profitMargins": 0.25,
        "revenueGrowth": 0.15,             # 15%
        "earningsGrowth": 0.18,
        "freeCashflow": 100_000_000_000,   # $100B
        "trailingPE": 28,
        "forwardPE": 24,
        "trailingEps": 6.50,
        "forwardEps": 7.50,
        "priceToBook": 5.0,
        "bookValue": 5.4,
        "currentRatio": 1.5,
        "pegRatio": 1.5,
        "currentPrice": 270,
        "marketCap": 3_500_000_000_000,
        "totalRevenue": 400_000_000_000,
        "sharesOutstanding": 14_700_000_000,
        "currency": "USD",
        "sector": "Technology",
        "dividendYield": 0.005,
        "heldPercentInstitutions": 0.65,
        "targetMeanPrice": 300,
        "numberOfAnalystOpinions": 40,
    }


@pytest.fixture
def info_weak_consumer():
    """약한 Consumer 종목 — 대부분 기준 미달이어야 함."""
    return {
        "returnOnEquity": 0.05,
        "debtToEquity": 250,
        "operatingMargins": 0.04,
        "grossMargins": 0.18,
        "profitMargins": 0.01,
        "revenueGrowth": -0.02,
        "earningsGrowth": -0.10,
        "freeCashflow": -50_000_000,
        "trailingPE": 80,
        "trailingEps": 0.50,
        "priceToBook": 12,
        "bookValue": 3.0,
        "currentRatio": 0.8,
        "currentPrice": 50,
        "marketCap": 5_000_000_000,
        "totalRevenue": 1_000_000_000,
        "sharesOutstanding": 100_000_000,
        "currency": "USD",
        "sector": "Consumer Cyclical",
    }


@pytest.fixture
def history_strong():
    """버핏 ROE 꾸준함 통과용 — 5년 모두 ROE 20%+."""
    return {
        "available": True,
        "years": ["2021", "2022", "2023", "2024", "2025"],
        "roe": [0.22, 0.25, 0.21, 0.23, 0.27],
        "revenue": [350e9, 365e9, 380e9, 395e9, 415e9],
        "eps": [5.0, 5.5, 5.8, 6.2, 7.0],
        "fcf": [90e9, 95e9, 100e9, 105e9, 110e9],
        "net_income": [80e9, 85e9, 90e9, 95e9, 105e9],
        "gross_margins": [0.43, 0.44, 0.45, 0.46, 0.47],
        "rd_ratios": [0.06, 0.07, 0.07, 0.08, 0.08],
        "roe_consistency": {
            "years_above_15pct": 5,
            "total_measured": 5,
            "all_positive": True,
            "passed_buffett_10yr_proxy": True,
        },
        "gross_margin_analysis": {"avg": 0.45, "std": 0.015, "stable": True, "measured": 5},
        "rd_analysis": {"latest": 0.08, "average": 0.072},
        "revenue_cagr": 0.043,
        "eps_cagr": 0.087,
    }
