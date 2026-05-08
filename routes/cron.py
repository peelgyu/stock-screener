"""Cron 엔드포인트 — 외부 cron이 호출 (GitHub Actions, cron-job.org 등)."""
import hmac
import os

from flask import Blueprint, current_app, jsonify, request

from data import daily_briefing
from data.cache import cache


cron_bp = Blueprint("cron", __name__)


@cron_bp.route("/cron/daily-briefing", methods=["POST", "GET"])
def cron_briefing():
    """외부 cron이 호출 — 매일 오전 9:30 KST에 브리핑 자동 생성.

    인증: X-Cron-Token 헤더 또는 ?token= 쿼리스트링 필수.
    환경변수 CRON_TOKEN과 일치해야 실행.
    """
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        return jsonify({"error": "CRON_TOKEN 환경변수 미설정"}), 503
    provided = request.headers.get("X-Cron-Token") or request.args.get("token") or ""
    # 상수 시간 비교 — 토큰 길이·내용 추측 timing attack 방어
    if not hmac.compare_digest(provided, expected):
        return jsonify({"error": "forbidden"}), 403

    try:
        briefing = daily_briefing.generate_briefing()
        path = daily_briefing.save_briefing(briefing)
        # 캐시도 갱신
        cache.set(f"daily_briefing:{briefing['date']}", briefing, ttl=3600)
        return jsonify({
            "ok": True,
            "date": briefing["date"],
            "saved_to": path,
            "summary": {
                "us_sp500": briefing.get("us_indices", {}).get("sp500"),
                "kr_kospi": briefing.get("kr_indices", {}).get("kospi"),
                "news_count": len(briefing.get("news_us", [])) + len(briefing.get("news_kr", [])),
            },
        })
    except Exception as e:
        current_app.logger.exception("briefing cron failed")
        return jsonify({"error": f"{type(e).__name__}: {str(e)[:200]}"}), 500
