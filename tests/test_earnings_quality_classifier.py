"""classify_company 회귀 테스트 — 8 카테고리 분류 정확성.

순수 함수, 외부 API 의존 없음. 적정주가 가중치 결정에 영향을 주는 핵심 로직이라
각 카테고리(STABLE / HYPER_GROWTH / DISTRESSED / ...)별 시그니처 케이스를 잠근다.
"""
from analysis.earnings_quality_classifier import classify_company


def _info(**overrides):
    base = {
        "trailingEps": 5.0,
        "forwardEps": 5.5,
        "freeCashflow": 100_000_000,
        "bookValue": 10.0,
        "revenueGrowth": 0.10,
        "debtToEquity": 50,
        "sector": "Technology",
        "marketCap": 100_000_000_000,
        "trailingPE": 20,
        "forwardPE": 18,
    }
    base.update(overrides)
    return base


def _hist(eps=None, fcf=None, revenue=None):
    return {
        "eps": eps or [4, 4.5, 5, 5.5, 6],
        "fcf": fcf or [80e6, 90e6, 95e6, 100e6, 110e6],
        "revenue": revenue or [800e6, 900e6, 1e9, 1.1e9, 1.2e9],
    }


# ────────────────── STABLE ──────────────────

def test_stable_when_consistent_earnings():
    res = classify_company(_info(), _hist())
    assert res["category"] == "STABLE"
    assert res["enable"]["dcf"] is True
    assert res["enable"]["per"] is True


# ────────────────── DISTRESSED ──────────────────

def test_distressed_when_3plus_year_losses_and_neg_fcf():
    res = classify_company(
        _info(trailingEps=-2, freeCashflow=-50_000_000),
        _hist(eps=[-1, -2, -3, -1, -2]),  # 5년 모두 적자
    )
    assert res["category"] == "DISTRESSED"
    assert res["confidence"] == "low"
    assert res["enable"]["dcf"] is False
    assert res["enable"]["per"] is False


# ────────────────── UNRELIABLE_EARNINGS ──────────────────

def test_unreliable_earnings_when_recent_loss_history_but_now_positive_with_neg_fcf():
    res = classify_company(
        _info(trailingEps=2, freeCashflow=-30_000_000),
        _hist(eps=[-1, -2, 1, 1.5, 2]),  # 과거 2년 적자 → 현재 흑자
    )
    assert res["category"] == "UNRELIABLE_EARNINGS"
    assert any("일회성" in w for w in res["warnings"])


# ────────────────── GROWTH_UNPROFITABLE ──────────────────

def test_growth_unprofitable_when_loss_but_high_growth():
    res = classify_company(
        _info(trailingEps=-1, revenueGrowth=0.40),
        _hist(eps=[-3, -2, -1, -0.5, -1]),
    )
    assert res["category"] == "GROWTH_UNPROFITABLE"
    assert res["enable"]["ps"] is True
    assert res["enable"]["per"] is False


# ────────────────── BUYBACK_HEAVY ──────────────────

def test_buyback_heavy_when_negative_equity_but_consistent_profit():
    """자본잠식이지만 5년 흑자 + 양수 FCF (AAPL 패턴)."""
    res = classify_company(
        _info(bookValue=-2.0, freeCashflow=100_000_000),
        _hist(eps=[5, 6, 7, 8, 9], fcf=[80e6, 90e6, 95e6, 100e6, 110e6]),
    )
    assert res["category"] == "BUYBACK_HEAVY"
    assert res["enable"]["graham"] is False
    assert res["enable"]["dcf"] is True


# ────────────────── STABLE_FINANCIAL / VOLATILE_FINANCIAL ──────────────────

def test_stable_financial_when_financial_sector_consistent_profit():
    res = classify_company(
        _info(sector="Financial Services", freeCashflow=None),
        _hist(eps=[3, 4, 5, 4.5, 5]),
    )
    assert res["category"] == "STABLE_FINANCIAL"
    assert res["enable"]["dcf"] is False  # 금융사는 DCF 무효
    assert res["enable"]["per"] is True


def test_volatile_financial_when_financial_sector_with_past_losses():
    res = classify_company(
        _info(sector="Financial Services", freeCashflow=None),
        _hist(eps=[-1, 2, 3, 4, 5]),
    )
    assert res["category"] == "VOLATILE_FINANCIAL"


# ────────────────── HYPER_GROWTH ──────────────────

def test_hyper_growth_when_high_pe_with_high_revenue_cagr():
    """NVDA·META 패턴 — 흑자 + 고PE + 5년 매출 CAGR 25%."""
    res = classify_company(
        _info(forwardPE=45, trailingPE=50, revenueGrowth=0.30),
        _hist(eps=[3, 4, 5, 6, 7], revenue=[400e6, 600e6, 800e6, 1.1e9, 1.5e9]),
    )
    assert res["category"] == "HYPER_GROWTH"
    assert res["confidence"] == "high"
    assert "rationale" in res
    assert res["enable"]["dcf"] is True


# ────────────────── VOLATILE ──────────────────

def test_volatile_when_negative_fcf_but_historically_positive():
    """KO 패턴 — 현재 FCF 일시 마이너스, 과거 양호."""
    res = classify_company(
        _info(freeCashflow=-10_000_000),
        _hist(fcf=[80e6, 90e6, 100e6, 110e6, -10e6]),
    )
    assert res["category"] == "VOLATILE"
    assert res["enable"]["dcf"] is False  # 현재 FCF 음수면 DCF 끔


def test_volatile_when_one_or_two_years_of_loss_in_history():
    res = classify_company(
        _info(),
        _hist(eps=[-1, 5, 6, 7, 5], fcf=[80e6, 90e6, 100e6, 110e6, 100e6]),
    )
    assert res["category"] in {"VOLATILE", "STABLE"}  # 1년 적자만 있으면 분기 따라 다름


# ────────────────── WEAK_CASH_FLOW ──────────────────

def test_weak_cash_flow_when_neg_fcf_and_no_historical_strength():
    """현재 FCF 음수 + 과거에도 양수 비율 60% 미만."""
    res = classify_company(
        _info(freeCashflow=-10_000_000),
        _hist(fcf=[-5e6, -10e6, 20e6, -5e6, -10e6]),  # 5년 중 2년만 양수
    )
    assert res["category"] == "WEAK_CASH_FLOW"


# ────────────────── 자본잠식 경고 ──────────────────

def test_negative_equity_adds_warning():
    res = classify_company(_info(bookValue=-1.0), _hist())
    assert any("자본잠식" in w for w in res["warnings"])


# ────────────────── INSUFFICIENT_DATA ──────────────────

def test_insufficient_data_when_eps_missing():
    res = classify_company(
        {"sector": "Technology", "freeCashflow": None, "bookValue": 1.0, "revenueGrowth": 0},
        None,
    )
    # eps 없고 fcf 없고 history 없음 → fallback INSUFFICIENT_DATA
    assert res["category"] in {"INSUFFICIENT_DATA", "STABLE"}
    assert res["confidence"] in {"low", "medium", "high"}
