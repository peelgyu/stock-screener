"""종목별 재무 특성 분류 — 어떤 밸류에이션 방법을 쓸지 결정."""


FINANCIAL_SECTORS = {"Financial Services", "Insurance"}


def classify_company(info: dict, history_data: dict | None) -> dict:
    """
    종목을 카테고리로 분류. Returns dict with category/confidence/label/warnings/note/enable.
    """
    eps = info.get("trailingEps")
    forward_eps = info.get("forwardEps")
    fcf = info.get("freeCashflow")
    bvps = info.get("bookValue")
    rev_growth = info.get("revenueGrowth") or 0
    de = info.get("debtToEquity")
    sector = info.get("sector") or ""

    is_financial = sector in FINANCIAL_SECTORS
    negative_equity = (bvps is not None and bvps < 0) or (de is not None and de < 0)

    warnings = []
    if negative_equity:
        warnings.append("자본잠식 — 순자산 기반 지표(PBR·Graham) 신뢰 불가")

    eps_history = (history_data or {}).get("eps") or []
    fcf_history = (history_data or {}).get("fcf") or []
    rev_history = (history_data or {}).get("revenue") or []
    eps_valid = [e for e in eps_history if e is not None]
    fcf_valid = [f for f in fcf_history if f is not None]

    eps_losses = sum(1 for e in eps_valid if e < 0)
    fcf_losses = sum(1 for f in fcf_valid if f < 0)
    fcf_positives = sum(1 for f in fcf_valid if f > 0)

    eps_current_positive = eps is not None and eps > 0
    fcf_current_negative = fcf is not None and fcf < 0
    fcf_current_positive = fcf is not None and fcf > 0
    fcf_missing = fcf is None

    # 역사적 FCF는 대체로 양수인지
    fcf_mostly_positive = len(fcf_valid) >= 2 and fcf_positives >= len(fcf_valid) * 0.6

    # 최근 매출 성장 양호
    has_recent_growth = False
    if len(rev_history) >= 2:
        valid_rev = [r for r in rev_history if r is not None]
        if len(valid_rev) >= 2 and valid_rev[0] > 0:
            recent_growth = (valid_rev[-1] - valid_rev[-2]) / valid_rev[-2] if valid_rev[-2] > 0 else 0
            has_recent_growth = recent_growth > 0.05

    # 금융섹터는 FCF 없는 게 정상
    if is_financial:
        # 금융사는 이익 + 배당·자본비율이 중요. FCF는 무시
        if eps_current_positive and eps_losses == 0:
            return {
                "category": "STABLE_FINANCIAL",
                "confidence": "high",
                "label": "금융 안정",
                "warnings": warnings,
                "note": "금융섹터 — DCF 대신 PER·Graham·애널리스트 중심",
                "enable": {"dcf": False, "per": True, "graham": not negative_equity, "analyst": True, "ps": False},
            }
        if eps_current_positive:
            return {
                "category": "VOLATILE_FINANCIAL",
                "confidence": "medium",
                "label": "금융 변동",
                "warnings": warnings + ["최근 일부년도 적자"],
                "note": "금융섹터 — PER·애널리스트 참고",
                "enable": {"dcf": False, "per": True, "graham": not negative_equity, "analyst": True, "ps": False},
            }

    # DISTRESSED: 3년 이상 적자 + 현재 FCF 적자
    if eps_losses >= 3 and fcf_current_negative:
        return {
            "category": "DISTRESSED",
            "confidence": "low",
            "label": "지속 적자·자금고갈 위험",
            "warnings": warnings + [f"최근 {len(eps_valid)}년 중 {eps_losses}년 EPS 적자"],
            "note": "펀더멘털 분석 신뢰도 매우 낮음 — 애널리스트 타겟 참고",
            "enable": {"dcf": False, "per": False, "graham": False, "analyst": True, "ps": False},
        }

    # UNRELIABLE_EARNINGS: 과거 다년 적자 + 현재 흑자 + FCF 음수 (일회성 이익)
    if eps_losses >= 2 and eps_current_positive and fcf_current_negative:
        return {
            "category": "UNRELIABLE_EARNINGS",
            "confidence": "low",
            "label": "일회성 이익 의심",
            "warnings": warnings + [
                f"과거 {eps_losses}년 적자 → 현재 흑자지만 FCF 여전히 적자 (일회성 이익 가능성)"
            ],
            "note": "PER 기반 평가 제외 — 애널리스트 타겟 중심",
            "enable": {"dcf": False, "per": False, "graham": False, "analyst": True, "ps": True},
        }

    # GROWTH_UNPROFITABLE: 적자 + 고성장 (25%+)
    if (eps is not None and eps < 0) and rev_growth >= 0.25:
        return {
            "category": "GROWTH_UNPROFITABLE",
            "confidence": "medium",
            "label": "적자 성장주",
            "warnings": warnings + [f"EPS 적자, 매출 성장률 {rev_growth*100:.1f}%"],
            "note": "이익 없어 PER·DCF 무효 — P/S 배수와 애널리스트 중심",
            "enable": {"dcf": False, "per": False, "graham": False, "analyst": True, "ps": True},
        }

    # BUYBACK_HEAVY: 자본잠식 + 꾸준한 이익 + 양수 FCF (AAPL 같은)
    if negative_equity and eps_losses == 0 and len(eps_valid) >= 2 and fcf_current_positive:
        return {
            "category": "BUYBACK_HEAVY",
            "confidence": "high",
            "label": "자사주매입형 우량주",
            "warnings": ["자사주 매입으로 장부상 자본잠식 (실제 부실 아님)"],
            "note": "Graham·PBR 무효 — DCF·PER·애널리스트 기반",
            "enable": {"dcf": True, "per": True, "graham": False, "analyst": True, "ps": False},
        }

    # WEAK_CASH_FLOW: 현재 FCF 음수이지만, 역사적으로 양수였으면 VOLATILE로 판정 (KO 같은 케이스)
    if fcf_current_negative and eps_current_positive:
        if fcf_mostly_positive:
            # 일시적 FCF 마이너스 — VOLATILE로 분류
            return {
                "category": "VOLATILE",
                "confidence": "medium",
                "label": "이익 변동성",
                "warnings": warnings + ["현재 FCF 일시 마이너스 (역사적으론 양호)"],
                "note": "DCF 제외 — PER·애널리스트 중심",
                "enable": {"dcf": False, "per": True, "graham": not negative_equity, "analyst": True, "ps": False},
            }
        return {
            "category": "WEAK_CASH_FLOW",
            "confidence": "medium",
            "label": "이익-현금흐름 괴리",
            "warnings": warnings + ["장부이익 양수지만 FCF 적자 — 회계 품질 주의"],
            "note": "DCF 제외 — PER·애널리스트·Graham 혼합",
            "enable": {"dcf": False, "per": True, "graham": not negative_equity, "analyst": True, "ps": True},
        }

    # VOLATILE: 3-5년 중 1-2년 적자
    if eps_losses >= 1 and eps_losses < 3 and len(eps_valid) >= 3:
        return {
            "category": "VOLATILE",
            "confidence": "medium",
            "label": "이익 변동성",
            "warnings": warnings + [f"최근 {len(eps_valid)}년 중 {eps_losses}년 EPS 적자"],
            "note": "PER 해석 신중 — 다년 평균 관점",
            "enable": {"dcf": True, "per": True, "graham": not negative_equity, "analyst": True, "ps": False},
        }

    # STABLE: 꾸준한 이익 + (양수 FCF 또는 FCF 데이터 없음)
    if eps_current_positive and (fcf_current_positive or fcf_missing or fcf_mostly_positive):
        conf = "high" if fcf_current_positive else "medium"
        w = warnings[:]
        if fcf_missing:
            w.append("FCF 데이터 없음 — DCF 신뢰도 낮음")
        return {
            "category": "STABLE",
            "confidence": conf,
            "label": "안정 수익 구조",
            "warnings": w,
            "note": "표준 평가 적용",
            "enable": {"dcf": fcf_current_positive or fcf_mostly_positive, "per": True, "graham": not negative_equity, "analyst": True, "ps": False},
        }

    # fallback
    return {
        "category": "INSUFFICIENT_DATA",
        "confidence": "low",
        "label": "데이터 부족",
        "warnings": warnings + ["재무제표 데이터 부족"],
        "note": "가능한 방법만 혼합",
        "enable": {"dcf": eps_current_positive, "per": eps_current_positive, "graham": not negative_equity, "analyst": True, "ps": False},
    }
