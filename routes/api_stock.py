"""종목 분석 API Blueprint — /api/analyze + 관련 lazy 로드 엔드포인트.

라우트:
- /api/analyze   POST  종목 종합 분석 (유명 투자자 5명 + 적정주가 + 재무 + 시황)
- /api/news      POST  종목별 뉴스 (네이버 API, 탭 클릭 시 lazy)
- /api/krx       POST  한국 종목 수급 (외국인·기관·공매도, lazy)
- /api/options   POST  옵션 체인 분석 (Max Pain, lazy)

helpers는 routes/_analysis_helpers.py로 분리.
"""
import concurrent.futures
import json as json_lib

from flask import Blueprint, current_app, jsonify, request

from analysis.evaluators import (
    safe_get, fmt_money,
    evaluate_positions,
    evaluate_buffett, buffett_strict_grade,
    evaluate_graham, lynch_category, evaluate_lynch, evaluate_fisher,
)
from analysis.fear_greed import evaluate_fear_greed
from analysis.history import get_historical_metrics
from analysis.market_regime import get_market_regime
from analysis.oneil import evaluate_oneil
from analysis.options import evaluate_options
from analysis.quality import evaluate_earnings_quality
from analysis.rs_rating import calculate_rs_rating
from analysis.sector_baseline import get_sector_thresholds
from analysis.valuation import calculate_fair_value
from analysis.verdict import generate_verdict

from data import dart_client, krx_client, naver_news, sec_client, kr_listing
from data.cache import cache
from data.fetcher import detect_fetch_error_type
from data.fx import get_usd_krw

from kr_stocks import KR_STOCKS, US_STOCKS_KR, get_kr_description, get_us_description, sector_kr
from routes._analysis_helpers import (
    _safe_call,
    _merge_dart_into_history,
    _populate_info_from_dart,
    _build_data_meta,
)
from utils import get_stock_data, is_safe_query, resolve_ticker


api_stock_bp = Blueprint("api_stock", __name__)


# ============================================================
# 라우트 — /api/analyze (메인 분석)
# ============================================================
@api_stock_bp.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.get_json(force=True, silent=True)
    if body is None or not body.get("ticker"):
        try:
            raw_body = request.get_data() or b""
            body = json_lib.loads(raw_body.decode("utf-8", errors="replace") or "{}")
        except Exception:
            body = body or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"error": "종목명 또는 티커를 입력해주세요."}), 400
    if not is_safe_query(raw_query):
        return jsonify({"error": "허용되지 않는 문자가 포함되었습니다. (영문·숫자·한글·점·하이픈만 허용)"}), 400

    ticker = resolve_ticker(raw_query)
    if ticker is None:
        ticker = raw_query.upper()

    # 응답 전체 캐시 — 같은 종목 반복 분석 시 즉시 응답
    # 30분 TTL: get_stock_data 캐시(2h)·DART(24h)·SEC(24h)와 일관 (UI도 "시세 15분 지연" 표기)
    analyze_cache_key = f"analyze_full:{ticker}"
    cached_response = cache.get(analyze_cache_key)
    if cached_response is not None:
        return jsonify(cached_response)

    data = get_stock_data(ticker)
    if data is None:
        error_type = detect_fetch_error_type(ticker)
        if error_type == "DATA_SOURCE_LIMITED":
            msg = "Yahoo Finance 데이터 제공이 일시 제한됐습니다. 2~3분 후 다시 시도해주세요. (한국 주식은 대체 데이터로 계속 사용 가능)"
            return jsonify({"error": msg, "type": error_type}), 503
        elif error_type == "DATA_SOURCE_DOWN":
            msg = "데이터 소스가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해주세요."
            return jsonify({"error": msg, "type": error_type}), 503
        else:
            return jsonify({"error": f"'{raw_query}' 종목을 찾을 수 없습니다. 티커·종목명을 확인해주세요."}), 404

    info = data["info"]
    hist = data.get("hist")
    stock = data.get("stock")

    sector = safe_get(info, "sector", "N/A")
    sector_t = get_sector_thresholds(sector if sector != "N/A" else None)

    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice", 0)
    market_cap = safe_get(info, "marketCap", 0)
    cap_str = fmt_money(market_cap, info)

    currency = safe_get(info, "currency", "USD")
    if currency == "KRW":
        price_str = f"₩{price:,.0f}"
    else:
        price_str = f"${price:,.2f}"

    is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")

    # 사업 한 줄 설명 — 4단 폴백 (한국 매핑 → 미국 매핑 → 한국어 sector·industry → 영문)
    description = None
    if is_kr:
        description = get_kr_description(ticker)
    else:
        description = get_us_description(ticker)
    if not description:
        # 한국어 sector·industry 조합 폴백 (영문보다 친화적)
        ind = safe_get(info, "industry", "")
        sector_ko = sector_kr(sector) if sector and sector != "N/A" else ""
        if sector_ko and ind:
            description = f"{sector_ko} · {ind}"
        elif sector_ko:
            description = sector_ko
    if not description:
        # 마지막 폴백: yfinance longBusinessSummary 첫 문장 (영문)
        summary = safe_get(info, "longBusinessSummary", "") or ""
        if summary:
            first_sentence = summary.split(". ")[0].strip()
            if len(first_sentence) > 200:
                first_sentence = first_sentence[:200].rsplit(" ", 1)[0] + "..."
            description = first_sentence + "." if first_sentence and not first_sentence.endswith(".") else first_sentence

    # 미국 종목 시총에 원화 환산 추가 표시
    cap_str_full = cap_str
    if not is_kr and market_cap and market_cap > 0:
        try:
            usd_krw = get_usd_krw()
            krw_cap = market_cap * usd_krw
            if krw_cap >= 1e12:
                krw_str = f"₩{krw_cap/1e12:,.1f}조"
            elif krw_cap >= 1e8:
                krw_str = f"₩{krw_cap/1e8:,.0f}억"
            else:
                krw_str = f"₩{krw_cap:,.0f}"
            cap_str_full = f"{cap_str} (≈ {krw_str})"
        except Exception:
            pass  # 환율 실패해도 영향 없음

    stock_info = {
        "name": safe_get(info, "longName", ticker),
        "sector": sector_kr(sector) if sector and sector != "N/A" else sector,  # 섹터 한국어
        "sectorEn": sector,  # 영문 sector도 보존 (분석 로직용)
        "industry": safe_get(info, "industry", "N/A"),
        "price": price_str,
        "marketCap": cap_str_full,  # 원화 환산 포함
        "logo": safe_get(info, "logo_url", ""),
        "description": description or "",
    }

    market_cache_key = f"market_regime:{is_kr}"

    # 외부 API 호출 wave 병렬화 — 독립 호출들을 ThreadPoolExecutor로 묶어 동시 실행
    # 7초 순차 → 3~4초 병렬 (가장 느린 한 호출 시간 + 작은 오버헤드)
    def _fetch_market():
        cached_md = cache.get(market_cache_key)
        if cached_md is not None:
            return cached_md
        md = _safe_call(get_market_regime, {"available": False}, is_kr=is_kr)
        if md.get("available"):
            cache.set(market_cache_key, md, ttl=900)
        return md

    with concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="analyze") as _ex:
        _fut_market = _ex.submit(_fetch_market)
        _fut_rs = _ex.submit(_safe_call, calculate_rs_rating, {"available": False}, ticker, hist)
        _fut_history = _ex.submit(_safe_call, get_historical_metrics, {"available": False}, stock)
        _fut_dart_fin = None
        _fut_dart_div = None
        _fut_sec_fin = None
        _fut_sec_ttm = None
        if is_kr and dart_client.is_available():
            _fut_dart_fin = _ex.submit(_safe_call, dart_client.fetch_financials, None, ticker, 5)
            _fut_dart_div = _ex.submit(_safe_call, dart_client.fetch_dividend, None, ticker)
        elif (not is_kr) and sec_client.is_available():
            _fut_sec_fin = _ex.submit(_safe_call, sec_client.fetch_financials, None, ticker, 6)
            _fut_sec_ttm = _ex.submit(_safe_call, sec_client.fetch_ttm_metrics, None, ticker)

        market_data = _fut_market.result(timeout=20)
        rs_data = _fut_rs.result(timeout=20)
        history_data = _fut_history.result(timeout=20)
        dart_fin = _fut_dart_fin.result(timeout=20) if _fut_dart_fin else None
        dart_div = _fut_dart_div.result(timeout=20) if _fut_dart_div else None
        sec_fin = _fut_sec_fin.result(timeout=20) if _fut_sec_fin else None
        sec_ttm = _fut_sec_ttm.result(timeout=20) if _fut_sec_ttm else None

    # 한국 주식(.KS/.KQ)은 DART 공시 데이터로 재무 history 보강 (더 정확)
    if is_kr:
        if dart_fin and dart_fin.get("years"):
            history_data = _merge_dart_into_history(history_data, dart_fin, info)
            info["_data_source_dart"] = True
            _populate_info_from_dart(info, dart_fin)
        # 배당 공시
        if dart_div:
            dps = dart_div.get("dps")
            y = dart_div.get("yield_pct")
            if dps is not None and info.get("dividendRate") is None:
                info["dividendRate"] = dps
            if y is not None and info.get("dividendYield") is None:
                info["dividendYield"] = y  # DART %를 그대로 저장 (yfinance 0.2.x+도 % 형식으로 통일)
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if dps and price and price > 0 and info.get("payoutRatio") is None:
                eps = info.get("trailingEps")
                if eps and eps > 0:
                    info["payoutRatio"] = dps / eps

    # 미국 주식은 SEC EDGAR 공시 데이터로 재무 history 보강 (yfinance 부실 응답 보완)
    # SEC EDGAR = Public Domain (17 USC §105) → 상업 이용 무제한
    if not is_kr:
        if sec_fin and sec_fin.get("years"):
            history_data = _merge_dart_into_history(history_data, sec_fin, info)  # 일반화된 병합
            info["_data_source_sec"] = True
            _populate_info_from_dart(info, sec_fin)  # 동일 인터페이스 — 미국에도 적용
            # SEC EPS·shares도 info에 보강
            eps_diluted = sec_fin.get("eps_diluted") or []
            shares = sec_fin.get("shares_outstanding") or []
            if eps_diluted:
                last_eps = next((v for v in reversed(eps_diluted) if v is not None), None)
                if last_eps and info.get("trailingEps") in (None, 0):
                    info["trailingEps"] = last_eps
            if shares:
                last_shares = next((v for v in reversed(shares) if v is not None), None)
                if last_shares and info.get("sharesOutstanding") in (None, 0):
                    info["sharesOutstanding"] = last_shares

        # SEC TTM 비율 — 미국 종목의 모든 비율 지표를 정부 공시 기반으로 정확화
        # yfinance 형식 변경(dividendYield 100배 등) 사고 영구 차단
        # D/E는 yfinance 정의(LT+ST debt만)가 더 정확해서 yfinance 우선 유지
        if sec_ttm:
            info["_sec_ttm"] = True

            def _safe_set(key, val, valid_check=lambda v: v is not None):
                if valid_check(val):
                    info[key] = val

            # 비율 지표 — SEC TTM이 yfinance 보다 정확 + 안정적
            if sec_ttm.get("roe") is not None:
                _safe_set("returnOnEquity", sec_ttm["roe"], lambda v: -2.0 <= v <= 5.0)
            if sec_ttm.get("operating_margin") is not None:
                _safe_set("operatingMargins", sec_ttm["operating_margin"], lambda v: -1.5 <= v <= 1.0)
            if sec_ttm.get("profit_margin") is not None:
                _safe_set("profitMargins", sec_ttm["profit_margin"], lambda v: -2.0 <= v <= 1.0)
            if sec_ttm.get("gross_margin") is not None:
                _safe_set("grossMargins", sec_ttm["gross_margin"], lambda v: -0.5 <= v <= 1.0)
            if sec_ttm.get("current_ratio") is not None:
                _safe_set("currentRatio", sec_ttm["current_ratio"], lambda v: 0.3 <= v <= 5.0)
            if sec_ttm.get("ttm_fcf") is not None:
                info["freeCashflow"] = sec_ttm["ttm_fcf"]
            if sec_ttm.get("ttm_revenue") is not None:
                info["totalRevenue"] = sec_ttm["ttm_revenue"]

            # PER/PBR/EPS/BPS — 자체 계산 (yfinance가 없거나 부정확할 때 보강)
            shares_out = info.get("sharesOutstanding") or sec_ttm.get("latest_shares")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            ni_ttm = sec_ttm.get("ttm_net_income")
            equity = sec_ttm.get("latest_equity")
            if shares_out and shares_out > 0 and price and price > 0:
                if ni_ttm is not None and ni_ttm > 0:
                    eps = ni_ttm / shares_out
                    info["trailingEps"] = eps
                    info["trailingPE"] = price / eps
                if equity and equity > 0:
                    bps = equity / shares_out
                    info["bookValue"] = bps
                    info["priceToBook"] = price / bps

    # 한국 주식 KRX 수급 — lazy load (별도 /api/krx 엔드포인트, 탭 클릭 시 fetch)
    krx_data = {"available": None, "lazy": True} if (is_kr and krx_client.is_available()) else None

    quality_data = _safe_call(evaluate_earnings_quality, {"available": False}, stock, info)
    fair_value = _safe_call(calculate_fair_value, {"available": False}, info, stock, history_data)
    if isinstance(fair_value, dict):
        fair_value["currency"] = safe_get(info, "currency", "USD")

    # 5인 평가자 병렬 실행 — 각 함수는 순수 dict 처리라 GIL 풀림은 적지만,
    # 향후 외부 호출(예: KIS API) 추가 시 즉시 효과. 현재도 약간 단축.
    _eval_tasks = {
        "buffett":  lambda: evaluate_buffett(info, sector_t, history_data=history_data, fair_value=fair_value),
        "graham":   lambda: evaluate_graham(info, sector_t, history_data=history_data),
        "lynch":    lambda: evaluate_lynch(info, sector_t, history_data=history_data),
        "lynch_cat": lambda: lynch_category(info, history_data=history_data),
        "oneil":    lambda: evaluate_oneil(info, ticker=ticker, hist=hist, rs_data=rs_data, market_data=market_data),
        "fisher":   lambda: evaluate_fisher(info, sector_t, history_data=history_data),
    }
    _eval_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as _ex:
        _futures = {_ex.submit(fn): name for name, fn in _eval_tasks.items()}
        for _f in concurrent.futures.as_completed(_futures, timeout=15):
            _name = _futures[_f]
            try:
                _eval_results[_name] = _f.result()
            except Exception:
                current_app.logger.exception(f"evaluator '{_name}' failed")
                _eval_results[_name] = [] if _name != "lynch_cat" else {"code": "UNCLASSIFIED", "label": "분류 불가", "desc": "오류"}

    investors = [
        {"name": "워렌 버핏", "label": "워렌 버핏이라면?", "sub": "가치투자", "icon": "buffett",
         "criteria": _eval_results.get("buffett", [])},
        {"name": "벤저민 그레이엄", "label": "벤저민 그레이엄이라면?", "sub": "안전마진", "icon": "graham",
         "criteria": _eval_results.get("graham", [])},
        {"name": "피터 린치", "label": "피터 린치라면?", "sub": "성장주", "icon": "lynch",
         "criteria": _eval_results.get("lynch", []),
         "category": _eval_results.get("lynch_cat", {"code": "UNCLASSIFIED", "label": "분류 불가", "desc": ""})},
        {"name": "윌리엄 오닐", "label": "윌리엄 오닐이라면?", "sub": "CAN SLIM", "icon": "oneil",
         "criteria": _eval_results.get("oneil", [])},
        {"name": "필립 피셔", "label": "필립 피셔라면?", "sub": "장기성장", "icon": "fisher",
         "criteria": _eval_results.get("fisher", [])},
    ]

    total_yes, total_count = 0, 0
    for inv in investors:
        yes = sum(1 for c in inv["criteria"] if c["passed"] is True)
        count = sum(1 for c in inv["criteria"] if c["passed"] is not None)
        inv["yes"] = yes
        inv["total"] = count
        inv["rate"] = round(yes / count * 100) if count > 0 else 0
        total_yes += yes
        total_count += count

        # 버핏 전용 엄격 등급 (9기준 중 통과 수 기반 — %가 아닌 절대값)
        if inv["name"] == "워렌 버핏":
            inv["strict_grade"] = buffett_strict_grade(yes, count)

    overall_rate = round(total_yes / total_count * 100) if total_count > 0 else 0
    # 등급 = 5인 대가 기준 통과율 (참고용 점수, 매수·매도 권유 아님)
    if overall_rate >= 70:
        grade, grade_text = "A", "기준 통과율 매우 높음"
    elif overall_rate >= 55:
        grade, grade_text = "B", "기준 통과율 높음"
    elif overall_rate >= 40:
        grade, grade_text = "C", "기준 통과율 보통"
    elif overall_rate >= 25:
        grade, grade_text = "D", "기준 통과율 낮음"
    else:
        grade, grade_text = "F", "기준 통과율 매우 낮음"

    overall = {"yes": total_yes, "total": total_count, "rate": overall_rate, "grade": grade, "gradeText": grade_text}

    fear_greed = _safe_call(evaluate_fear_greed, {"score": None, "label": "데이터 부족", "indicators": []}, data)
    positions = _safe_call(evaluate_positions, {"short": [], "long": [], "sentiment": "중립", "sentimentDetail": ""}, data)
    # 옵션 체인은 느리므로 별도 엔드포인트(/api/options)로 분리 — 탭 클릭 시 로드
    options = {"available": None, "lazy": True}

    verdict = _safe_call(generate_verdict, {"decision": "관망", "color": "yellow", "reasons": [], "warnings": [], "confidence": "low"},
                         overall, rs_data, market_data, fair_value, quality_data, fear_greed)

    response_data = {
        "stock": stock_info,
        "ticker": ticker,
        "sectorThresholds": sector_t,
        "marketRegime": market_data,
        "rsRating": rs_data,
        "history": history_data,
        "quality": quality_data,
        "fairValue": fair_value,
        "verdict": verdict,
        "fearGreed": fear_greed,
        "positions": positions,
        "options": options,
        "investors": investors,
        "overall": overall,
        "krx": krx_data,
        "dataWarnings": info.get("_data_warnings", []),
        "dataMeta": _build_data_meta(info, ticker, is_kr, history_data),
    }
    # 응답 캐시 — 30분 (다음 동일 ticker 분석 요청에 즉시 응답)
    cache.set(analyze_cache_key, response_data, ttl=1800)
    return jsonify(response_data)


# ============================================================
# /api/news — 종목 뉴스 (lazy)
# ============================================================
@api_stock_bp.route("/api/news", methods=["POST"])
def analyze_news():
    """종목 관련 뉴스 — 네이버 검색 API. 탭 클릭 시 lazy load.

    회사명을 query로 사용 (티커보다 매칭 잘됨). 한국 종목은 longName,
    미국 종목은 longName 또는 한국어 매핑 우선.
    제목·요약·링크만 반환 (저작권 안전 — 본문은 원본 사이트로).
    """
    body = request.get_json(force=True, silent=True) or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
    if not naver_news.is_available():
        return jsonify({"available": False, "error": "뉴스 API 미설정 (NAVER_CLIENT_ID 환경변수 필요)"}), 200

    ticker = resolve_ticker(raw_query) or raw_query.upper()
    is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")

    # 검색어 결정 — 회사명 우선, 없으면 티커
    search_query = ""
    if is_kr:
        # 한국: KR_STOCKS reverse lookup ("005930.KS" → "삼성전자")
        for name, (tk, _eng) in KR_STOCKS.items():
            if tk == ticker:
                search_query = name
                break
        if not search_query:
            # KRX listing fallback
            try:
                code = ticker.split(".")[0]
                listings = kr_listing.get_listings() if hasattr(kr_listing, "get_listings") else []
                for item in (listings or []):
                    if item.get("code") == code:
                        search_query = item.get("name") or ""
                        break
            except Exception:
                pass
    else:
        # 미국: US_STOCKS_KR reverse lookup ("AAPL" → "애플"), 없으면 티커
        for kr_name, tk in US_STOCKS_KR.items():
            if tk == ticker:
                search_query = kr_name
                break

    if not search_query:
        search_query = ticker

    items = naver_news.fetch_news(search_query, display=8, sort="date")
    if items is None:
        return jsonify({"available": False, "error": "뉴스 일시 불가"}), 200

    return jsonify({
        "available": True,
        "query": search_query,
        "ticker": ticker,
        "items": items,
        "source": "네이버 검색 API",
    })


# ============================================================
# /api/krx — 한국 종목 수급 (lazy)
# ============================================================
@api_stock_bp.route("/api/krx", methods=["POST"])
def analyze_krx():
    """한국 종목 수급 정보 — 외국인·기관·공매도. 탭 클릭 시 lazy load."""
    body = request.get_json(force=True, silent=True) or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
    ticker = resolve_ticker(raw_query) or raw_query.upper()
    if not (ticker.endswith(".KS") or ticker.endswith(".KQ")):
        return jsonify({"available": False, "error": "한국 종목만 지원"}), 400
    if not krx_client.is_available():
        return jsonify({"available": False, "error": "KRX 클라이언트 미설치"}), 503

    # 외부 호출 timeout 방어 — 8초 안에 못 받으면 None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(krx_client.fetch_all, ticker)
            result = future.result(timeout=8.0)
            return jsonify(result)
    except concurrent.futures.TimeoutError:
        current_app.logger.warning(f"KRX timeout for {ticker}")
        return jsonify({"available": False, "error": "KRX 응답 지연 — 잠시 후 다시 시도"}), 200
    except Exception:
        current_app.logger.exception("krx fail")
        return jsonify({"available": False, "error": "KRX 데이터 일시 불가"}), 200


# ============================================================
# /api/options — 옵션 체인 분석 (lazy)
# ============================================================
@api_stock_bp.route("/api/options", methods=["POST"])
def analyze_options_route():
    """옵션 체인 + Max Pain 분석 — 탭 클릭 시 lazy load. 외부 호출 무거우므로 분리."""
    body = request.get_json(force=True, silent=True)
    if body is None or not body.get("ticker"):
        try:
            raw_body = request.get_data() or b""
            body = json_lib.loads(raw_body.decode("utf-8", errors="replace") or "{}")
        except Exception:
            body = body or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
    ticker = resolve_ticker(raw_query) or raw_query.upper()
    data = get_stock_data(ticker)
    if data is None:
        return jsonify({"available": False, "error": "종목을 찾을 수 없습니다"}), 404
    try:
        return jsonify(evaluate_options(data))
    except Exception as e:
        current_app.logger.exception("options fail")
        return jsonify({"available": False, "error": str(e)[:200]}), 500
