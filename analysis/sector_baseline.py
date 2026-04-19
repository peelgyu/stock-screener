"""섹터별 상대 기준값. 고정 테이블(시장 중앙값 근사)."""

SECTOR_THRESHOLDS = {
    "Technology": {
        "per_max": 35, "pbr_max": 8.0, "de_max": 100,
        "om_min": 0.18, "gm_min": 0.50, "pm_min": 0.12,
        "roe_min": 0.15, "rev_growth_min": 0.10, "median_pe": 32,
    },
    "Communication Services": {
        "per_max": 28, "pbr_max": 5.0, "de_max": 150,
        "om_min": 0.15, "gm_min": 0.45, "pm_min": 0.10,
        "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 25,
    },
    "Financial Services": {
        "per_max": 20, "pbr_max": 2.5, "de_max": 400,
        "om_min": 0.25, "gm_min": 0.60, "pm_min": 0.18,
        "roe_min": 0.10, "rev_growth_min": 0.05, "median_pe": 15,
    },
    "Healthcare": {
        "per_max": 30, "pbr_max": 6.0, "de_max": 120,
        "om_min": 0.15, "gm_min": 0.50, "pm_min": 0.10,
        "roe_min": 0.13, "rev_growth_min": 0.08, "median_pe": 24,
    },
    "Consumer Cyclical": {
        "per_max": 25, "pbr_max": 5.0, "de_max": 150,
        "om_min": 0.08, "gm_min": 0.30, "pm_min": 0.06,
        "roe_min": 0.12, "rev_growth_min": 0.07, "median_pe": 20,
    },
    "Consumer Defensive": {
        "per_max": 25, "pbr_max": 5.0, "de_max": 120,
        "om_min": 0.10, "gm_min": 0.30, "pm_min": 0.07,
        "roe_min": 0.12, "rev_growth_min": 0.04, "median_pe": 22,
    },
    "Energy": {
        "per_max": 18, "pbr_max": 3.0, "de_max": 100,
        "om_min": 0.08, "gm_min": 0.25, "pm_min": 0.06,
        "roe_min": 0.10, "rev_growth_min": 0.00, "median_pe": 14,
    },
    "Industrials": {
        "per_max": 25, "pbr_max": 4.0, "de_max": 120,
        "om_min": 0.10, "gm_min": 0.25, "pm_min": 0.07,
        "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 22,
    },
    "Utilities": {
        "per_max": 22, "pbr_max": 2.5, "de_max": 250,
        "om_min": 0.15, "gm_min": 0.35, "pm_min": 0.10,
        "roe_min": 0.08, "rev_growth_min": 0.02, "median_pe": 20,
    },
    "Real Estate": {
        "per_max": 28, "pbr_max": 3.0, "de_max": 250,
        "om_min": 0.30, "gm_min": 0.50, "pm_min": 0.20,
        "roe_min": 0.07, "rev_growth_min": 0.04, "median_pe": 24,
    },
    "Basic Materials": {
        "per_max": 20, "pbr_max": 3.0, "de_max": 120,
        "om_min": 0.08, "gm_min": 0.20, "pm_min": 0.05,
        "roe_min": 0.10, "rev_growth_min": 0.02, "median_pe": 17,
    },
}

DEFAULT_THRESHOLDS = {
    "per_max": 22, "pbr_max": 3.5, "de_max": 120,
    "om_min": 0.12, "gm_min": 0.35, "pm_min": 0.08,
    "roe_min": 0.12, "rev_growth_min": 0.05, "median_pe": 20,
}

# 섹터별 적정주가 composite 가중치 (dcf / per / graham / analyst)
# Graham은 자산집약 섹터(금융/유틸/부동산)에서만 비중 크게
SECTOR_WEIGHTS = {
    "Technology":             {"dcf": 0.35, "per": 0.35, "graham": 0.05, "analyst": 0.25},
    "Communication Services": {"dcf": 0.35, "per": 0.35, "graham": 0.05, "analyst": 0.25},
    "Healthcare":             {"dcf": 0.30, "per": 0.35, "graham": 0.10, "analyst": 0.25},
    "Consumer Cyclical":      {"dcf": 0.30, "per": 0.30, "graham": 0.15, "analyst": 0.25},
    "Consumer Defensive":     {"dcf": 0.30, "per": 0.25, "graham": 0.20, "analyst": 0.25},
    "Industrials":            {"dcf": 0.30, "per": 0.25, "graham": 0.20, "analyst": 0.25},
    "Basic Materials":        {"dcf": 0.25, "per": 0.25, "graham": 0.30, "analyst": 0.20},
    "Energy":                 {"dcf": 0.25, "per": 0.25, "graham": 0.30, "analyst": 0.20},
    "Financial Services":     {"dcf": 0.20, "per": 0.25, "graham": 0.35, "analyst": 0.20},
    "Utilities":              {"dcf": 0.25, "per": 0.25, "graham": 0.30, "analyst": 0.20},
    "Real Estate":            {"dcf": 0.15, "per": 0.20, "graham": 0.45, "analyst": 0.20},
}
DEFAULT_WEIGHTS = {"dcf": 0.30, "per": 0.30, "graham": 0.15, "analyst": 0.25}


def get_sector_thresholds(sector: str | None) -> dict:
    if not sector:
        return {**DEFAULT_THRESHOLDS, "sector": "Unknown"}
    t = SECTOR_THRESHOLDS.get(sector)
    if t:
        return {**t, "sector": sector}
    return {**DEFAULT_THRESHOLDS, "sector": sector}


def get_sector_weights(sector: str | None) -> dict:
    if sector and sector in SECTOR_WEIGHTS:
        return SECTOR_WEIGHTS[sector]
    return DEFAULT_WEIGHTS
