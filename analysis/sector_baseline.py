"""섹터별 상대 기준값. 고정 테이블(시장 중앙값 근사)."""

SECTOR_THRESHOLDS = {
    "Technology": {
        "per_max": 30, "pbr_max": 6.0, "de_max": 80,
        "om_min": 0.18, "gm_min": 0.50, "pm_min": 0.12,
        "roe_min": 0.15, "rev_growth_min": 0.10, "median_pe": 28,
    },
    "Communication Services": {
        "per_max": 25, "pbr_max": 4.0, "de_max": 120,
        "om_min": 0.15, "gm_min": 0.45, "pm_min": 0.10,
        "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 22,
    },
    "Financial Services": {
        "per_max": 18, "pbr_max": 2.0, "de_max": 300,
        "om_min": 0.25, "gm_min": 0.60, "pm_min": 0.18,
        "roe_min": 0.10, "rev_growth_min": 0.05, "median_pe": 14,
    },
    "Healthcare": {
        "per_max": 28, "pbr_max": 5.0, "de_max": 100,
        "om_min": 0.15, "gm_min": 0.50, "pm_min": 0.10,
        "roe_min": 0.13, "rev_growth_min": 0.08, "median_pe": 22,
    },
    "Consumer Cyclical": {
        "per_max": 22, "pbr_max": 4.0, "de_max": 120,
        "om_min": 0.08, "gm_min": 0.30, "pm_min": 0.06,
        "roe_min": 0.12, "rev_growth_min": 0.07, "median_pe": 18,
    },
    "Consumer Defensive": {
        "per_max": 22, "pbr_max": 4.0, "de_max": 100,
        "om_min": 0.10, "gm_min": 0.30, "pm_min": 0.07,
        "roe_min": 0.12, "rev_growth_min": 0.04, "median_pe": 20,
    },
    "Energy": {
        "per_max": 15, "pbr_max": 2.5, "de_max": 80,
        "om_min": 0.08, "gm_min": 0.25, "pm_min": 0.06,
        "roe_min": 0.10, "rev_growth_min": 0.00, "median_pe": 12,
    },
    "Industrials": {
        "per_max": 22, "pbr_max": 3.5, "de_max": 100,
        "om_min": 0.10, "gm_min": 0.25, "pm_min": 0.07,
        "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 20,
    },
    "Utilities": {
        "per_max": 20, "pbr_max": 2.0, "de_max": 200,
        "om_min": 0.15, "gm_min": 0.35, "pm_min": 0.10,
        "roe_min": 0.08, "rev_growth_min": 0.02, "median_pe": 18,
    },
    "Real Estate": {
        "per_max": 25, "pbr_max": 2.5, "de_max": 200,
        "om_min": 0.30, "gm_min": 0.50, "pm_min": 0.20,
        "roe_min": 0.07, "rev_growth_min": 0.04, "median_pe": 22,
    },
    "Basic Materials": {
        "per_max": 18, "pbr_max": 2.5, "de_max": 100,
        "om_min": 0.08, "gm_min": 0.20, "pm_min": 0.05,
        "roe_min": 0.10, "rev_growth_min": 0.02, "median_pe": 15,
    },
}

DEFAULT_THRESHOLDS = {
    "per_max": 20, "pbr_max": 3.0, "de_max": 100,
    "om_min": 0.12, "gm_min": 0.35, "pm_min": 0.08,
    "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 18,
}


def get_sector_thresholds(sector: str | None) -> dict:
    if not sector:
        return {**DEFAULT_THRESHOLDS, "sector": "Unknown"}
    t = SECTOR_THRESHOLDS.get(sector)
    if t:
        return {**t, "sector": sector}
    return {**DEFAULT_THRESHOLDS, "sector": sector}
