"""시장·검색 API Blueprint — 종목 분석 외 가벼운 메타 라우트.

라우트:
- /api/search           검색 자동완성 (KR_STOCKS + KRX + Yahoo)
- /api/most_active      거래량 TOP 10
- /api/briefing/summary 일일 시황 모달용 요약
- /api/cache/stats      캐시 통계 (운영 메타 + 헬스체크)
"""
import json as json_lib
import urllib.parse
import urllib.request

from flask import Blueprint, current_app, jsonify, request

from data import daily_briefing, kr_listing
from data.cache import cache
from analysis.most_active import get_most_active
from kr_stocks import search_kr_stocks
from utils import is_safe_query


api_market_bp = Blueprint("api_market", __name__)


@api_market_bp.route("/api/search", methods=["GET"])
def search_stocks():
    """검색 우선순위:
    1) 친근 별명 (KR_STOCKS 89개) — 정확 일치 + 부분 일치
    2) KRX 전체 상장 종목 (~2,500개) — 정식 종목명·코드 매칭
    3) Yahoo Finance 검색 — 미국·해외 ETF 등

    Yahoo amplification 방어 — 동일 쿼리 5분 캐시 (외부 API 부하 차단).
    """
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    # 입력 검증 — 비정상 문자열은 즉시 거절 (Yahoo 호출 방지)
    if len(q) > 30 or not is_safe_query(q):
        return jsonify([])

    cache_key = f"search:{q.lower()}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return jsonify(cached_result)

    results = []
    seen = set()

    def _add(item):
        if item["symbol"] not in seen:
            seen.add(item["symbol"])
            results.append(item)

    # 1) 친근 별명 매핑 우선
    for r in search_kr_stocks(q):
        _add(r)

    # 2) KRX 전체 종목 (정식 종목명) — 잡주·중소형주 커버
    if len(results) < 8:
        for r in kr_listing.search_listings(q, limit=8):
            _add(r)

    # 3) Yahoo 검색 — 미국·해외 (위 둘에서 8개 안 채워졌을 때)
    if len(results) < 6:
        try:
            encoded = urllib.parse.quote(q)
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=6&newsCount=0&listsCount=0"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=5)
            data = json_lib.loads(resp.read())
            for item in data.get("quotes", []):
                symbol = item.get("symbol", "")
                if not symbol:
                    continue
                _add({
                    "symbol": symbol,
                    "name": item.get("shortname", "") or item.get("longname", ""),
                    "engName": item.get("longname", ""),
                    "exchange": item.get("exchDisp", ""),
                    "sector": item.get("sector", "") or item.get("industry", ""),
                })
        except Exception as e:
            current_app.logger.debug(f"Yahoo /api/search supplemental failed: {type(e).__name__}")

    final = results[:8]
    cache.set(cache_key, final, ttl=300)  # 5분 캐시 — Yahoo 부하 amplification 차단
    return jsonify(final)


@api_market_bp.route("/api/most_active")
def api_most_active():
    """거래량 TOP 10 (US + KR) — 사이드바용. 15분 캐시."""
    cache_key = "most_active:v1"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return jsonify(cached_result)
    try:
        result = get_most_active()
        cache.set(cache_key, result, ttl=900)  # 15분 캐시
        return jsonify(result)
    except Exception as e:
        current_app.logger.exception("most_active fail")
        return jsonify({"us": [], "kr": [], "error": str(e)[:200]}), 500


@api_market_bp.route("/api/briefing/summary")
def briefing_summary():
    """모달 팝업용 경량 요약 — 지수·환율·공포탐욕·뉴스 3건만."""
    try:
        briefing = daily_briefing.get_or_generate()
    except Exception:
        current_app.logger.exception("briefing summary failed")
        return jsonify({"available": False}), 200

    if not briefing:
        return jsonify({"available": False}), 200

    return jsonify({
        "available": True,
        "date": briefing.get("date"),
        "weekday_kr": briefing.get("weekday_kr"),
        "us_indices": briefing.get("us_indices"),
        "kr_indices": briefing.get("kr_indices"),
        "fx": briefing.get("fx"),
        "fear_greed": briefing.get("fear_greed"),
        "top_news_kr": (briefing.get("news_kr") or [])[:3],
        "top_news_us": (briefing.get("news_us") or [])[:3],
    })


@api_market_bp.route("/api/cache/stats")
def cache_stats():
    """캐시 통계 + 헬스체크 (Railway healthcheckPath용)."""
    return jsonify(cache.stats())
