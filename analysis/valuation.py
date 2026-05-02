"""DCF / PER / Graham / 애널리스트 / P/S 기반 적정주가 추정 — 종목 카테고리 차등 적용."""

import math
from analysis.sector_baseline import get_sector_thresholds, get_sector_weights
from analysis.earnings_quality_classifier import classify_company


# 섹터별 적정 P/S (매출 배수) — 적자 성장주 평가용
SECTOR_PS_MEDIAN = {
    "Technology": 7.0,
    "Communication Services": 4.0,
    "Healthcare": 5.0,
    "Consumer Cyclical": 1.5,
    "Consumer Defensive": 1.5,
    "Financial Services": 3.0,
    "Energy": 1.2,
    "Industrials": 1.8,
    "Utilities": 2.0,
    "Real Estate": 6.0,
    "Basic Materials": 1.5,
}


# DCF 보수화 상수 — 회계사 자문 반영 (2026-04-29)
# - 영구성장률 1.5%: 인플레 이하의 매우 보수적 가정 (현재 운영 정책)
# - 할인율: WACC 동적 산출 (CAPM 자기자본비용 + 차입이자율 가중평균)
TERMINAL_GROWTH = 0.015

# 무위험수익률 (10년물 국채 근사)
RF_US = 0.043   # 미국 10Y Treasury ~4.3%
RF_KR = 0.033   # 한국 10년물 국채 ~3.3%
ERP = 0.055     # Damodaran 글로벌 주식 위험 프리미엄

# 할인율 안전 범위 (이상치 보호)
WACC_MIN = 0.075
WACC_MAX = 0.140


def _calc_wacc(info: dict, ticker: str | None = None) -> dict:
    """WACC 산출 — CAPM 자기자본비용과 차입이자율의 시가 가중평균.

    공식:
      WACC = (E/V) * Re + (D/V) * Rd * (1 - Tc)
      Re   = Rf + β * ERP                      (CAPM)
      Rd   = 이자비용 / 총부채                 (재무제표 추정)

    누락 시 안전한 기본값으로 폴백 후 안전 범위([7.5%, 14%]) 클램프.
    """
    is_kr = bool(ticker and (ticker.endswith(".KS") or ticker.endswith(".KQ")))
    rf = RF_KR if is_kr else RF_US
    tax_rate = 0.22 if is_kr else 0.21

    # 1) 자기자본비용 Re — CAPM
    beta = info.get("beta")
    # 한국 종목은 yfinance.beta가 None이면 KOSPI 대비 자체 계산
    if (beta is None or beta == 0) and is_kr and ticker:
        try:
            from data.beta_calc import calc_kr_beta
            calc = calc_kr_beta(ticker)
            if calc is not None:
                beta = calc
        except Exception:
            pass
    try:
        beta = float(beta) if beta is not None else 1.0
    except (TypeError, ValueError):
        beta = 1.0
    # 비정상 베타 클램프
    if beta < 0.3:
        beta = 0.8
    elif beta > 2.5:
        beta = 2.0
    re = rf + beta * ERP

    # 2) 차입이자율 Rd — 이자비용/총부채, 없으면 Rf + 1.5%p (BBB급 회사채 스프레드 근사)
    interest_expense = info.get("interestExpense")
    total_debt = info.get("totalDebt")
    rd = None
    if interest_expense and total_debt and total_debt > 0:
        try:
            rd = abs(float(interest_expense)) / float(total_debt)
        except (TypeError, ValueError):
            rd = None
    if rd is None or rd <= 0 or rd > 0.20:
        rd = rf + 0.015

    # 3) 자본구조 가중치 (시가총액 vs 부채 장부가)
    market_cap = info.get("marketCap")
    try:
        equity_v = float(market_cap) if market_cap and market_cap > 0 else None
    except (TypeError, ValueError):
        equity_v = None
    try:
        debt_v = float(total_debt) if total_debt and total_debt > 0 else 0.0
    except (TypeError, ValueError):
        debt_v = 0.0

    if not equity_v or equity_v <= 0:
        # 시총 정보 없으면 자기자본비용만 사용 (보수적)
        wacc_raw = re
        we, wd = 1.0, 0.0
    else:
        v = equity_v + debt_v
        we = equity_v / v
        wd = debt_v / v
        wacc_raw = we * re + wd * rd * (1 - tax_rate)

    wacc = max(WACC_MIN, min(WACC_MAX, wacc_raw))
    return {
        "wacc": round(wacc, 4),
        "wacc_raw": round(wacc_raw, 4),
        "cost_of_equity": round(re, 4),
        "cost_of_debt": round(rd, 4),
        "beta": round(beta, 2),
        "weight_equity": round(we, 3),
        "weight_debt": round(wd, 3),
        "rf": rf,
        "tax_rate": tax_rate,
    }


def _dcf_fair_value(fcf, shares, growth_5y=0.10, terminal_growth=TERMINAL_GROWTH, discount=0.10):
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return None
    # 안전장치: 할인율이 영구성장률보다 충분히 커야 영구가치 발산 안 함
    if discount - terminal_growth < 0.01:
        discount = terminal_growth + 0.01
    pv = 0.0
    current_fcf = fcf
    for yr in range(1, 6):
        current_fcf *= (1 + growth_5y)
        pv += current_fcf / ((1 + discount) ** yr)
    terminal_fcf = current_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount - terminal_growth)
    pv += terminal_value / ((1 + discount) ** 5)
    return pv / shares


def _graham_number(eps, bvps):
    if not eps or not bvps or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def _ps_fair_value(info, sector):
    """P/S 배수법 — 섹터 중앙값 P/S × 주당매출."""
    revenue = info.get("totalRevenue")
    shares = info.get("sharesOutstanding")
    if not revenue or not shares or revenue <= 0 or shares <= 0:
        return None
    sps = revenue / shares  # sales per share
    target_ps = SECTOR_PS_MEDIAN.get(sector, 2.5)
    return sps * target_ps


def calculate_fair_value(info: dict, stock, history_data: dict | None = None) -> dict:
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price:
        return {"available": False}

    sector = info.get("sector")
    st = get_sector_thresholds(sector)
    base_weights = get_sector_weights(sector)

    # 종목 카테고리 분류
    quality_class = classify_company(info, history_data)

    fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    trailing_eps = info.get("trailingEps")
    forward_eps = info.get("forwardEps")
    eps = forward_eps if (forward_eps and forward_eps > 0) else trailing_eps
    eps_source = "forward" if (forward_eps and forward_eps > 0) else "trailing"
    bvps = info.get("bookValue")
    analyst_target = info.get("targetMeanPrice")

    # 동적 성장률 (DCF용)
    dynamic_growth = 0.10
    rg = info.get("revenueGrowth")
    eg = info.get("earningsGrowth")
    if rg is not None and eg is not None:
        dynamic_growth = min(0.25, max(0.02, (rg + eg) / 2))
    elif rg is not None:
        dynamic_growth = min(0.25, max(0.02, rg))
    elif eg is not None:
        dynamic_growth = min(0.25, max(0.02, eg))

    # WACC 동적 산출 — 회계사 자문 (자본비용 + 차입이자율 가중평균)
    ticker_str = None
    try:
        ticker_str = getattr(stock, "ticker", None) if stock else None
    except Exception:
        ticker_str = None
    wacc_info = _calc_wacc(info, ticker_str)
    discount_rate = wacc_info["wacc"]

    enable = quality_class["enable"]
    methods = {}
    excluded = []

    # 1) DCF — WACC 할인율 + 영구성장률 1.5% (보수)
    if enable["dcf"]:
        dcf_fv = _dcf_fair_value(fcf, shares, growth_5y=dynamic_growth,
                                 discount=discount_rate, terminal_growth=TERMINAL_GROWTH)
        if dcf_fv is not None:
            methods["dcf"] = {
                "fair_value": round(dcf_fv, 2),
                "upside_pct": round((dcf_fv - current_price) / current_price * 100, 1),
                "assumptions": {
                    "growth_5y": round(dynamic_growth, 3),
                    "terminal_growth": TERMINAL_GROWTH,
                    "discount_rate": discount_rate,
                    "wacc_breakdown": wacc_info,
                },
            }
        else:
            excluded.append({"method": "DCF", "reason": "FCF 음수 또는 데이터 부족"})
    else:
        excluded.append({"method": "DCF", "reason": f"카테고리 '{quality_class['label']}' — DCF 부적합"})

    # 2) PER
    if enable["per"] and eps and eps > 0:
        per_fv = eps * st["median_pe"]
        methods["per_based"] = {
            "fair_value": round(per_fv, 2),
            "upside_pct": round((per_fv - current_price) / current_price * 100, 1),
            "assumption_pe": st["median_pe"],
            "eps_used": round(eps, 2),
            "eps_source": eps_source,
            "sector": st.get("sector", "Unknown"),
        }
    elif not enable["per"]:
        excluded.append({"method": "PER", "reason": f"카테고리 '{quality_class['label']}' — 이익 왜곡 의심"})
    else:
        excluded.append({"method": "PER", "reason": "EPS 음수 또는 데이터 부족"})

    # 3) Graham
    if enable["graham"]:
        graham_fv = _graham_number(trailing_eps, bvps)
        if graham_fv is not None:
            methods["graham_number"] = {
                "fair_value": round(graham_fv, 2),
                "upside_pct": round((graham_fv - current_price) / current_price * 100, 1),
            }
        else:
            excluded.append({"method": "Graham", "reason": "EPS·BVPS 음수 또는 데이터 부족"})
    else:
        excluded.append({"method": "Graham", "reason": f"카테고리 '{quality_class['label']}' — 순자산 지표 무효"})

    # 4) 애널리스트 목표가
    if enable["analyst"] and analyst_target and analyst_target > 0:
        methods["analyst_target"] = {
            "fair_value": round(float(analyst_target), 2),
            "upside_pct": round((analyst_target - current_price) / current_price * 100, 1),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        }
    elif enable["analyst"]:
        excluded.append({"method": "애널리스트", "reason": "목표가 데이터 없음"})

    # 5) P/S 기반
    if enable["ps"]:
        ps_fv = _ps_fair_value(info, sector)
        if ps_fv is not None:
            methods["ps_based"] = {
                "fair_value": round(ps_fv, 2),
                "upside_pct": round((ps_fv - current_price) / current_price * 100, 1),
                "sector_ps_median": SECTOR_PS_MEDIAN.get(sector, 2.5),
            }
        else:
            excluded.append({"method": "P/S", "reason": "매출 데이터 부족"})

    # ===== Composite 계산 =====
    # 카테고리에 맞는 가중치 재구성
    method_weight_key = {
        "dcf": "dcf",
        "per_based": "per",
        "graham_number": "graham",
        "analyst_target": "analyst",
        "ps_based": "analyst",  # P/S는 애널리스트와 비슷한 무게로 처리
    }

    available_methods = {}
    for method_name, method_data in methods.items():
        fair_val = method_data["fair_value"]
        weight_key = method_weight_key.get(method_name, "analyst")
        base_w = base_weights.get(weight_key, 0.25)
        # UNRELIABLE_EARNINGS/GROWTH_UNPROFITABLE면 애널리스트 가중치 증폭
        if quality_class["category"] in ("UNRELIABLE_EARNINGS", "GROWTH_UNPROFITABLE", "DISTRESSED"):
            if method_name == "analyst_target":
                base_w = max(base_w, 0.60)
            elif method_name == "ps_based":
                base_w = 0.30
        available_methods[method_name] = (fair_val, base_w)

    if not available_methods:
        return {
            "available": False,
            "current_price": round(current_price, 2),
            "quality_class": quality_class,
            "excluded_methods": excluded,
        }

    # 극단 이상치 제거: 현재가 대비 10배 이상 또는 1/10 이하는 outlier (계산오류 가능성)
    filtered_methods = {}
    for name, (val, w) in available_methods.items():
        ratio = val / current_price if current_price > 0 else 0
        if 0.1 <= ratio <= 10.0:
            filtered_methods[name] = (val, w)
        else:
            reason = f"outlier 제외 (적정가/현재가 비율 {ratio:.2f}x — 비정상)"
            excluded.append({"method": {"dcf":"DCF","per_based":"PER","graham_number":"Graham","analyst_target":"애널리스트","ps_based":"P/S"}.get(name, name), "reason": reason})

    if not filtered_methods:
        return {
            "available": False,
            "current_price": round(current_price, 2),
            "quality_class": quality_class,
            "excluded_methods": excluded,
            "note": "모든 평가법이 이상치로 제외됨 — 수동 검토 필요",
        }

    available_methods = filtered_methods
    total_w = sum(w for _, w in available_methods.values())
    composite = sum(v * w for v, w in available_methods.values()) / total_w
    upside = (composite - current_price) / current_price * 100

    used_weights = {k: round(w / total_w, 2) for k, (_, w) in available_methods.items()}

    # 판정
    if quality_class["confidence"] == "low":
        verdict_prefix = "⚠ 신뢰도 낮음 — "
    else:
        verdict_prefix = ""

    if upside >= 20:
        verdict = f"{verdict_prefix}적정가 대비 큰 상승여력 (+20% 이상)"
    elif upside >= 10:
        verdict = f"{verdict_prefix}적정가 대비 상승여력 (+10~20%)"
    elif upside >= -10:
        verdict = f"{verdict_prefix}현재가가 적정가 근처 (±10%)"
    elif upside >= -20:
        verdict = f"{verdict_prefix}적정가 대비 프리미엄 반영 (10~20%)"
    else:
        verdict = f"{verdict_prefix}적정가 대비 큰 프리미엄 (20% 이상)"

    return {
        "current_price": round(current_price, 2),
        "dcf": methods.get("dcf"),
        "per_based": methods.get("per_based"),
        "graham_number": methods.get("graham_number", {}).get("fair_value") if methods.get("graham_number") else None,
        "analyst_target": methods.get("analyst_target"),
        "ps_based": methods.get("ps_based"),
        "composite_fair_value": round(composite, 2),
        "upside_pct": round(upside, 1),
        "verdict": verdict,
        "sector": st.get("sector", "Unknown"),
        "weights_used": used_weights,
        "quality_class": {
            "category": quality_class["category"],
            "label": quality_class["label"],
            "confidence": quality_class["confidence"],
            "warnings": quality_class["warnings"],
            "note": quality_class["note"],
        },
        "excluded_methods": excluded,
        "available": True,
    }
