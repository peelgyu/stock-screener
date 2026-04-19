"""DCF / PER / Graham / 애널리스트 기반 적정주가 추정 — 섹터 가중치."""

import math
from analysis.sector_baseline import get_sector_thresholds, get_sector_weights


def _dcf_fair_value(fcf: float, shares: float, growth_5y=0.10, terminal_growth=0.03, discount=0.09):
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return None
    pv = 0.0
    current_fcf = fcf
    for _ in range(1, 6):
        current_fcf *= (1 + growth_5y)
        pv += current_fcf / ((1 + discount) ** _)
    terminal_fcf = current_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount - terminal_growth)
    pv += terminal_value / ((1 + discount) ** 5)
    return pv / shares


def _graham_number(eps: float, bvps: float):
    if not eps or not bvps or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def calculate_fair_value(info: dict, stock) -> dict:
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price:
        return {"available": False}

    sector = info.get("sector")
    st = get_sector_thresholds(sector)
    weights = get_sector_weights(sector)

    fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    eps = info.get("trailingEps")
    bvps = info.get("bookValue")
    analyst_target = info.get("targetMeanPrice")

    # 성장률 반영 DCF: 실제 매출/이익 성장률로 1단계 성장률 조정 (보수적 상한)
    dynamic_growth = 0.10
    rg = info.get("revenueGrowth")
    eg = info.get("earningsGrowth")
    if rg is not None and eg is not None:
        dynamic_growth = min(0.20, max(0.02, (rg + eg) / 2))
    elif rg is not None:
        dynamic_growth = min(0.20, max(0.02, rg))
    elif eg is not None:
        dynamic_growth = min(0.20, max(0.02, eg))

    methods = {}

    # 1) DCF
    dcf_fv = _dcf_fair_value(fcf, shares, growth_5y=dynamic_growth)
    if dcf_fv is not None:
        methods["dcf"] = {
            "fair_value": round(dcf_fv, 2),
            "upside_pct": round((dcf_fv - current_price) / current_price * 100, 1),
            "assumptions": {"growth_5y": round(dynamic_growth, 3), "terminal_growth": 0.03, "discount_rate": 0.09},
        }

    # 2) PER 기반 (섹터 중앙값)
    per_fv = None
    if eps and eps > 0:
        per_fv = eps * st["median_pe"]
        methods["per_based"] = {
            "fair_value": round(per_fv, 2),
            "upside_pct": round((per_fv - current_price) / current_price * 100, 1),
            "assumption_pe": st["median_pe"],
            "sector": st.get("sector", "Unknown"),
        }

    # 3) Graham Number
    graham_fv = _graham_number(eps, bvps)
    if graham_fv is not None:
        methods["graham_number"] = {
            "fair_value": round(graham_fv, 2),
            "upside_pct": round((graham_fv - current_price) / current_price * 100, 1),
        }

    # 4) 애널리스트 목표가
    analyst_fv = None
    if analyst_target and analyst_target > 0:
        analyst_fv = float(analyst_target)
        methods["analyst_target"] = {
            "fair_value": round(analyst_fv, 2),
            "upside_pct": round((analyst_fv - current_price) / current_price * 100, 1),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        }

    # 섹터 가중 composite (사용 가능한 방법만 선별 후 정규화)
    available_methods = {}
    if dcf_fv is not None:
        available_methods["dcf"] = (dcf_fv, weights["dcf"])
    if per_fv is not None:
        available_methods["per"] = (per_fv, weights["per"])
    if graham_fv is not None:
        available_methods["graham"] = (graham_fv, weights["graham"])
    if analyst_fv is not None:
        available_methods["analyst"] = (analyst_fv, weights["analyst"])

    if not available_methods:
        return {"available": False, "current_price": round(current_price, 2)}

    total_w = sum(w for _, w in available_methods.values())
    composite = sum(v * w for v, w in available_methods.values()) / total_w
    upside = (composite - current_price) / current_price * 100

    # 사용된 가중치 정규화해서 표기
    used_weights = {k: round(w / total_w, 2) for k, (_, w) in available_methods.items()}

    if upside >= 20:
        verdict = "크게 저평가 (적정가 대비 20%+ 할인)"
    elif upside >= 10:
        verdict = "저평가 (적정가 대비 10~20% 할인)"
    elif upside >= -10:
        verdict = "현재가가 적정가 근처 (±10%)"
    elif upside >= -20:
        verdict = "고평가 (적정가 대비 10~20% 프리미엄)"
    else:
        verdict = "크게 고평가 (적정가 대비 20%+ 프리미엄)"

    return {
        "current_price": round(current_price, 2),
        "dcf": methods.get("dcf"),
        "per_based": methods.get("per_based"),
        "graham_number": methods.get("graham_number", {}).get("fair_value") if "graham_number" in methods else None,
        "analyst_target": methods.get("analyst_target"),
        "composite_fair_value": round(composite, 2),
        "upside_pct": round(upside, 1),
        "verdict": verdict,
        "sector": st.get("sector", "Unknown"),
        "weights_used": used_weights,
        "available": True,
    }
