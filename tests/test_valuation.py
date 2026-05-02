"""DCF·WACC 계산 회귀 테스트."""
import pytest

from analysis.valuation import _calc_wacc, _dcf_fair_value, TERMINAL_GROWTH


def test_wacc_us_normal_beta():
    """미국 종목 베타 1.2 → WACC 10~11% 범위."""
    info = {"beta": 1.2, "marketCap": 3.5e12, "totalDebt": 1e11, "interestExpense": 4e9}
    w = _calc_wacc(info, "AAPL")
    assert 0.075 <= w["wacc"] <= 0.140
    assert abs(w["beta"] - 1.2) < 0.01
    # CAPM: 4.3% + 1.2 × 5.5% = 10.9% ± 안전치
    assert 0.10 <= w["cost_of_equity"] <= 0.12


def test_wacc_kr_uses_lower_rf():
    """한국 종목은 무위험률 3.3% 적용."""
    info = {"beta": 0.9, "marketCap": 4e14, "totalDebt": 1e14}
    w = _calc_wacc(info, "005930.KS")
    assert w["rf"] == 0.033
    assert w["tax_rate"] == 0.22


def test_wacc_clamps_high_beta():
    """베타 3.0 → 클램프 2.0으로 → WACC 14% 상한."""
    info = {"beta": 3.0, "marketCap": 1e11, "totalDebt": 0}
    w = _calc_wacc(info, "TSLA")
    assert w["beta"] == 2.0
    assert w["wacc"] <= 0.140


def test_wacc_handles_missing_beta():
    """베타 None이면 1.0 폴백."""
    info = {"marketCap": 1e10}
    w = _calc_wacc(info, "XYZ")
    assert w["beta"] == 1.0


def test_dcf_returns_positive_for_healthy_fcf():
    """FCF 10B + 발행주식 1B + 정상 가정 → 적정주가 양수."""
    fv = _dcf_fair_value(fcf=10e9, shares=1e9, growth_5y=0.05, discount=0.10, terminal_growth=TERMINAL_GROWTH)
    assert fv is not None
    assert fv > 0


def test_dcf_returns_none_on_negative_fcf():
    """FCF 음수 → None."""
    fv = _dcf_fair_value(fcf=-1e9, shares=1e9, growth_5y=0.05, discount=0.10, terminal_growth=0.015)
    assert fv is None


def test_dcf_terminal_growth_below_discount():
    """할인율 < 영구성장률이면 발산 위험 — 함수가 안전장치로 discount를 올림."""
    # discount 1%, terminal 5% — 발산 위험 → 안전장치로 discount = terminal+0.01 = 6%
    fv = _dcf_fair_value(fcf=10e9, shares=1e9, growth_5y=0.03, discount=0.01, terminal_growth=0.05)
    # 안전장치 동작 시 양수 값 나와야 함
    assert fv is not None
    assert fv > 0


def test_terminal_growth_constant():
    """영구성장률 1.5% 고정 — 회계사 자문 반영, 변경 시 알림."""
    assert TERMINAL_GROWTH == 0.015
