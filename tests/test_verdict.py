"""generate_verdict 회귀 테스트 — 6개 입력 dict → 등급(A~F)·점수·reasons/warnings.

순수 함수, 외부 API 의존 없음. 가중치(특히 quality_class confidence=low → 절반)와
분류 카테고리(DISTRESSED 등) 페널티가 의도대로 적용되는지를 잠근다.
"""
from analysis.verdict import generate_verdict


def _empty_overall():
    return {"rate": 0, "yes": 0, "total": 0}


# ────────────────── 등급 분류 ──────────────────

def test_grade_a_when_score_high():
    overall = {"rate": 80, "yes": 8, "total": 10}                       # +2
    rs = {"available": True, "rs_composite": 90}                         # +2
    market = {"available": True, "passed_canslim_m": True, "benchmark_name": "S&P 500"}  # +1
    fair = {"available": True, "upside_pct": 30, "quality_class": {"confidence": "high"}}  # +2
    out = generate_verdict(overall, rs, market, fair, None, None)
    assert out["score"] >= 4
    assert "A 등급" in out["decision"]
    assert out["color"] == "green"
    assert out["confidence"] == "high"


def test_grade_f_when_score_very_low():
    overall = {"rate": 10, "yes": 1, "total": 10}                        # +0, warning
    rs = {"available": True, "rs_composite": 20}                         # warning
    market = {"available": True, "direction": "하락장"}                   # -2
    fair = {"available": True, "upside_pct": -30,
            "quality_class": {"confidence": "high", "category": "DISTRESSED"}}  # -2 -2
    quality = {"available": True, "quality_score": 30}                   # -1
    out = generate_verdict(overall, rs, market, fair, quality, None)
    assert out["score"] <= -3
    assert "F 등급" in out["decision"]
    assert out["color"] == "red"


def test_grade_c_when_score_neutral():
    overall = {"rate": 50, "yes": 5, "total": 10}                        # +1
    out = generate_verdict(overall, None, None, None, None, None)
    assert "C 등급" in out["decision"]


# ────────────────── reasons/warnings 누적 ──────────────────

def test_reasons_capped_at_4():
    overall = {"rate": 80, "yes": 8, "total": 10}
    rs = {"available": True, "rs_composite": 90}
    market = {"available": True, "passed_canslim_m": True, "benchmark_name": "S&P 500"}
    fair = {"available": True, "upside_pct": 30, "quality_class": {"confidence": "high"}}
    quality = {"available": True, "quality_score": 90}
    fg = {"score": 20}
    out = generate_verdict(overall, rs, market, fair, quality, fg)
    assert len(out["reasons"]) <= 4
    assert len(out["warnings"]) <= 4


def test_reasons_fallback_when_empty():
    out = generate_verdict(_empty_overall(), None, None, None, None, None)
    assert out["reasons"] == ["특이점 없음"]


# ────────────────── quality_class confidence 가중치 ──────────────────

def test_low_confidence_halves_fair_value_impact():
    """confidence=low이면 적정가 +20% upside가 +2 대신 +1만 줘야."""
    overall = _empty_overall()
    fair_high = {"available": True, "upside_pct": 25, "quality_class": {"confidence": "high"}}
    fair_low = {"available": True, "upside_pct": 25, "quality_class": {"confidence": "low"}}
    high = generate_verdict(overall, None, None, fair_high, None, None)
    low = generate_verdict(overall, None, None, fair_low, None, None)
    assert high["score"] - low["score"] == 1  # 2 vs 1


# ────────────────── 카테고리 페널티 ──────────────────

def test_distressed_category_adds_warning_and_penalty():
    overall = {"rate": 50, "yes": 5, "total": 10}                        # +1
    fair = {"available": True, "upside_pct": 5,
            "quality_class": {"confidence": "high", "category": "DISTRESSED"}}  # -2
    out = generate_verdict(overall, None, None, fair, None, None)
    assert any("적자" in w or "자금" in w for w in out["warnings"])
    assert out["score"] <= 0


def test_unreliable_earnings_warning_no_score_change():
    overall = _empty_overall()
    base = generate_verdict(overall, None, None, None, None, None)
    fair = {"available": True, "upside_pct": 0,
            "quality_class": {"confidence": "high", "category": "UNRELIABLE_EARNINGS"}}
    out = generate_verdict(overall, None, None, fair, None, None)
    assert out["score"] == base["score"]  # 점수 변화 없음
    assert any("일회성" in w for w in out["warnings"])


# ────────────────── 공포·탐욕 ──────────────────

def test_extreme_fear_adds_contrarian_bonus():
    overall = _empty_overall()
    base = generate_verdict(overall, None, None, None, None, None)
    out = generate_verdict(overall, None, None, None, None, {"score": 20})
    assert out["score"] == base["score"] + 1
    assert any("역발상" in r or "공포" in r for r in out["reasons"])


def test_extreme_greed_adds_overheating_warning():
    overall = _empty_overall()
    base = generate_verdict(overall, None, None, None, None, None)
    out = generate_verdict(overall, None, None, None, None, {"score": 85})
    assert out["score"] == base["score"] - 1
    assert any("과열" in w or "탐욕" in w for w in out["warnings"])
