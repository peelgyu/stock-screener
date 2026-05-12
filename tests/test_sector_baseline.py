"""sector_baseline 회귀 테스트 — 섹터 lookup + 폴백.

config/sector_defaults.json 오버라이드는 모듈 로드 시점 1회만 적용되므로
이 테스트는 모듈에 이미 로드된 표만 검증한다.
"""
from analysis.sector_baseline import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    SECTOR_THRESHOLDS,
    SECTOR_WEIGHTS,
    get_sector_thresholds,
    get_sector_weights,
)


# ────────────────── 표 형태 검증 ──────────────────

def test_all_sector_thresholds_have_required_keys():
    required = {"per_max", "pbr_max", "de_max", "om_min", "gm_min", "pm_min",
                "roe_min", "rev_growth_min", "median_pe"}
    for sector, t in SECTOR_THRESHOLDS.items():
        missing = required - set(t.keys())
        assert not missing, f"{sector}: missing {missing}"


def test_all_sector_weights_sum_close_to_one():
    for sector, w in SECTOR_WEIGHTS.items():
        total = sum(w.values())
        assert 0.99 <= total <= 1.01, f"{sector} weights sum = {total} (must be 1.0)"


def test_default_weights_sum_to_one():
    assert 0.99 <= sum(DEFAULT_WEIGHTS.values()) <= 1.01


# ────────────────── get_sector_thresholds ──────────────────

def test_get_thresholds_returns_known_sector():
    t = get_sector_thresholds("Technology")
    assert t["sector"] == "Technology"
    assert t["per_max"] == SECTOR_THRESHOLDS["Technology"]["per_max"]


def test_get_thresholds_returns_default_for_unknown_sector():
    t = get_sector_thresholds("WeirdSector")
    assert t["sector"] == "WeirdSector"
    for k, v in DEFAULT_THRESHOLDS.items():
        assert t[k] == v


def test_get_thresholds_returns_unknown_for_none():
    t = get_sector_thresholds(None)
    assert t["sector"] == "Unknown"


def test_get_thresholds_returns_unknown_for_empty_string():
    t = get_sector_thresholds("")
    assert t["sector"] == "Unknown"


# ────────────────── get_sector_weights ──────────────────

def test_get_weights_returns_known_sector():
    w = get_sector_weights("Real Estate")
    assert w == SECTOR_WEIGHTS["Real Estate"]
    assert w["graham"] == 0.45  # 자산집약 섹터 → Graham 비중 큼


def test_get_weights_returns_default_for_unknown():
    assert get_sector_weights("WeirdSector") == DEFAULT_WEIGHTS


def test_get_weights_returns_default_for_none():
    assert get_sector_weights(None) == DEFAULT_WEIGHTS


# ────────────────── 도메인 로직 회귀 ──────────────────

def test_financial_services_has_low_dcf_high_graham():
    """금융섹터는 DCF 비중 낮고 Graham 높아야 (자산기반 평가 우세)."""
    w = SECTOR_WEIGHTS["Financial Services"]
    assert w["dcf"] <= 0.25
    assert w["graham"] >= 0.30


def test_technology_has_low_graham():
    """기술섹터는 Graham 비중 낮아야 (성장주는 자산기반 평가 부적합)."""
    assert SECTOR_WEIGHTS["Technology"]["graham"] <= 0.10


def test_energy_per_lower_than_tech():
    """경기순환 섹터(Energy)의 PER 상한이 Tech보다 낮아야 자연."""
    assert SECTOR_THRESHOLDS["Energy"]["per_max"] < SECTOR_THRESHOLDS["Technology"]["per_max"]
