"""5인 평가자 회귀 테스트.

목적: 평가 로직이 의도치 않게 바뀌면 테스트가 깨져 알려준다.
이 테스트는 외부 API(yfinance/DART)를 호출하지 않고 순수 함수만 검증한다.
"""
import pytest


def _passed_count(criteria):
    return sum(1 for c in criteria if c.get("passed") is True)


def _by_name_substring(criteria, sub):
    """기준 항목 중 name에 sub가 들어간 첫 항목 반환."""
    for c in criteria:
        if sub in c.get("name", ""):
            return c
    return None


# ────────────────── 워렌 버핏 ──────────────────

def test_buffett_strong_passes_majority(app_module, info_strong_tech, sector_thresholds_tech, history_strong):
    """강한 Tech 종목은 버핏 9기준 중 절반 이상 통과해야."""
    res = app_module.evaluate_buffett(info_strong_tech, sector_thresholds_tech, history_data=history_strong)
    assert isinstance(res, list)
    assert len(res) >= 5
    passed = _passed_count(res)
    assert passed >= 5, f"강한 종목인데 {passed}/{len(res)}만 통과 — 버핏 로직 회귀 의심"


def test_buffett_roe_pass_when_high(app_module, info_strong_tech, sector_thresholds_tech, history_strong):
    """ROE 30%면 ROE 기준은 무조건 통과."""
    res = app_module.evaluate_buffett(info_strong_tech, sector_thresholds_tech, history_data=history_strong)
    roe_item = _by_name_substring(res, "ROE >=")
    assert roe_item is not None
    assert roe_item["passed"] is True


def test_buffett_strict_grade_full(app_module):
    """9/9면 A+ 등급."""
    grade = app_module.buffett_strict_grade(9, 9)
    assert grade["grade"].startswith("A")


def test_buffett_strict_grade_zero(app_module):
    """0/9면 F 등급."""
    grade = app_module.buffett_strict_grade(0, 9)
    assert grade["grade"] == "F"


def test_buffett_weak_fails_majority(app_module, info_weak_consumer, sector_thresholds_tech):
    """약한 종목은 통과율 낮아야 (회귀 발생 시 통과율 의심)."""
    res = app_module.evaluate_buffett(info_weak_consumer, sector_thresholds_tech)
    passed = _passed_count(res)
    total = len([r for r in res if r.get("passed") in (True, False)])
    if total > 0:
        rate = passed / total
        assert rate < 0.5, f"약한 종목인데 통과율 {rate:.0%} — 채점 너무 후함"


# ────────────────── 그레이엄 ──────────────────

def test_graham_returns_list(app_module, info_strong_tech, sector_thresholds_tech):
    res = app_module.evaluate_graham(info_strong_tech, sector_thresholds_tech)
    assert isinstance(res, list)
    assert len(res) >= 4


def test_graham_per_check_existence(app_module, info_strong_tech, sector_thresholds_tech):
    """그레이엄은 PER 기준을 반드시 포함해야."""
    res = app_module.evaluate_graham(info_strong_tech, sector_thresholds_tech)
    per_item = _by_name_substring(res, "PER")
    assert per_item is not None


# ────────────────── 린치 ──────────────────

def test_lynch_returns_criteria(app_module, info_strong_tech, sector_thresholds_tech):
    res = app_module.evaluate_lynch(info_strong_tech, sector_thresholds_tech)
    assert isinstance(res, list)
    assert len(res) >= 3


def test_lynch_category_classification(app_module, info_strong_tech):
    """린치 카테고리 분류 — code·label 키 보장."""
    cat = app_module.lynch_category(info_strong_tech)
    assert "code" in cat
    assert "label" in cat
    # 강한 시총 큰 종목은 STALWART 또는 FAST_GROWER 가능성 큼
    assert cat["code"] in ("FAST_GROWER", "STALWART", "SLOW_GROWER", "ASSET_PLAY",
                          "TURNAROUND", "CYCLICAL", "UNCLASSIFIED")


# ────────────────── 피셔 ──────────────────

def test_fisher_returns_list(app_module, info_strong_tech, sector_thresholds_tech, history_strong):
    res = app_module.evaluate_fisher(info_strong_tech, sector_thresholds_tech, history_data=history_strong)
    assert isinstance(res, list)
    assert len(res) >= 4


# ────────────────── 안정성 / 엣지 케이스 ──────────────────

def test_buffett_handles_empty_info(app_module, sector_thresholds_tech):
    """빈 info dict 줘도 크래시 없이 N/A 응답."""
    res = app_module.evaluate_buffett({}, sector_thresholds_tech)
    assert isinstance(res, list)
    # 모든 항목이 None passed (N/A) 이거나 false
    na_or_false = all(r.get("passed") in (None, False) for r in res)
    assert na_or_false


def test_graham_handles_empty(app_module, sector_thresholds_tech):
    res = app_module.evaluate_graham({}, sector_thresholds_tech)
    assert isinstance(res, list)


def test_safe_get_returns_default(app_module):
    """safe_get은 None을 default로 변환 (NaN 처리는 SafeJSONProvider 담당)."""
    assert app_module.safe_get({}, "missing", default="DEF") == "DEF"
    assert app_module.safe_get({"x": None}, "x", default=0) == 0
    # 정상값은 그대로
    assert app_module.safe_get({"x": 42}, "x", default=0) == 42
