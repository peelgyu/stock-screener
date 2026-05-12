"""evaluate_oneil 회귀 테스트 — CAN SLIM 7기준(C/A/N/S/L/I/M).

순수 함수, info dict + 선택적 rs_data/market_data만 받는다.
각 기준이 통과/실패/데이터없음 셋 다 의도대로 분기되는지를 잠근다.
"""
from analysis.oneil import evaluate_oneil


def _by_prefix(results, prefix):
    """이름이 'C:'/'A:'/'N:' 등으로 시작하는 첫 항목 반환."""
    for r in results:
        if r["name"].startswith(prefix):
            return r
    return None


def test_returns_seven_criteria():
    """CAN SLIM 7기준 모두 반환."""
    res = evaluate_oneil({})
    assert len(res) == 7
    for prefix in ["C:", "A:", "N:", "S:", "L:", "I:", "M:"]:
        assert _by_prefix(res, prefix) is not None


# ────────────────── C: 분기 EPS 성장 ──────────────────

def test_c_passes_when_quarterly_growth_high():
    res = evaluate_oneil({"earningsQuarterlyGrowth": 0.30})
    assert _by_prefix(res, "C:")["passed"] is True


def test_c_fails_when_quarterly_growth_low():
    res = evaluate_oneil({"earningsQuarterlyGrowth": 0.10})
    assert _by_prefix(res, "C:")["passed"] is False


def test_c_none_when_missing():
    res = evaluate_oneil({})
    assert _by_prefix(res, "C:")["passed"] is None


# ────────────────── A: 연간 EPS 성장 ──────────────────

def test_a_passes_at_threshold():
    res = evaluate_oneil({"earningsGrowth": 0.25})
    assert _by_prefix(res, "A:")["passed"] is True


def test_a_fails_below_threshold():
    res = evaluate_oneil({"earningsGrowth": 0.20})
    assert _by_prefix(res, "A:")["passed"] is False


# ────────────────── N: 52주 고가 근처 ──────────────────

def test_n_passes_near_52w_high():
    res = evaluate_oneil({"currentPrice": 90, "fiftyTwoWeekHigh": 100})
    assert _by_prefix(res, "N:")["passed"] is True


def test_n_fails_far_from_52w_high():
    res = evaluate_oneil({"currentPrice": 70, "fiftyTwoWeekHigh": 100})
    assert _by_prefix(res, "N:")["passed"] is False


def test_n_uses_regular_market_price_when_current_missing():
    res = evaluate_oneil({"regularMarketPrice": 90, "fiftyTwoWeekHigh": 100})
    assert _by_prefix(res, "N:")["passed"] is True


# ────────────────── S: 거래량 ──────────────────

def test_s_passes_when_volume_surge():
    res = evaluate_oneil({"volume": 200, "averageVolume": 100})
    assert _by_prefix(res, "S:")["passed"] is True


def test_s_fails_when_volume_normal():
    res = evaluate_oneil({"volume": 110, "averageVolume": 100})
    assert _by_prefix(res, "S:")["passed"] is False


# ────────────────── L: RS Rating ──────────────────

def test_l_passes_when_rs_high():
    res = evaluate_oneil({}, rs_data={"available": True, "rs_composite": 90})
    assert _by_prefix(res, "L:")["passed"] is True


def test_l_fails_when_rs_low():
    res = evaluate_oneil({}, rs_data={"available": True, "rs_composite": 50})
    assert _by_prefix(res, "L:")["passed"] is False


def test_l_none_when_rs_unavailable():
    res = evaluate_oneil({}, rs_data={"available": False})
    assert _by_prefix(res, "L:")["passed"] is None


def test_l_none_when_rs_data_missing():
    res = evaluate_oneil({})
    assert _by_prefix(res, "L:")["passed"] is None


# ────────────────── I: 기관 보유 ──────────────────

def test_i_passes_when_institutional_high():
    res = evaluate_oneil({"heldPercentInstitutions": 0.50})
    assert _by_prefix(res, "I:")["passed"] is True


def test_i_fails_when_institutional_low():
    res = evaluate_oneil({"heldPercentInstitutions": 0.10})
    assert _by_prefix(res, "I:")["passed"] is False


# ────────────────── M: 시장 방향 ──────────────────

def test_m_passes_in_uptrend():
    res = evaluate_oneil({}, market_data={"available": True, "passed_canslim_m": True,
                                           "direction": "상승장 (Confirmed Uptrend)"})
    m = _by_prefix(res, "M:")
    assert m["passed"] is True
    assert "상승장" in m["value"]


def test_m_fails_in_downtrend():
    res = evaluate_oneil({}, market_data={"available": True, "passed_canslim_m": False,
                                           "direction": "하락장"})
    assert _by_prefix(res, "M:")["passed"] is False


def test_m_none_when_market_unavailable():
    res = evaluate_oneil({}, market_data={"available": False})
    assert _by_prefix(res, "M:")["passed"] is None
