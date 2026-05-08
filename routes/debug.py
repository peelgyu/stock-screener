"""Debug 엔드포인트 — 운영 진단용 (loopback/사설 IP에서만 응답).

운영서버에서 누군가 실수로 STOCKINTO_DEBUG=1을 켜도 외부 IP는 접근 불가
(DART 키 prefix·env 길이 leak 방지).
"""
import ipaddress
import json as json_lib
import os

from flask import Blueprint, jsonify, request

from data import dart_client


debug_bp = Blueprint("debug", __name__)


def _is_local_or_private_ip() -> bool:
    """클라이언트 IP가 loopback/사설 대역인지 — 디버그·진단 게이팅용."""
    try:
        ip = ipaddress.ip_address(request.remote_addr or "")
        return ip.is_loopback or ip.is_private
    except (ValueError, TypeError):
        return False


def _debug_enabled() -> bool:
    """디버그 엔드포인트는 STOCKINTO_DEBUG=1 + 로컬/사설 IP에서만 활성."""
    if os.getenv("STOCKINTO_DEBUG", "0") != "1":
        return False
    return _is_local_or_private_ip()


@debug_bp.route("/api/debug/echo", methods=["POST"])
def debug_echo():
    """body가 어떻게 들어오는지 확인 (STOCKINTO_DEBUG=1 + 사설 IP 일 때만)."""
    if not _debug_enabled():
        return jsonify({"error": "Not Found"}), 404
    raw_bytes = request.get_data()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    body_json = request.get_json(force=True, silent=True)
    try:
        manual = json_lib.loads(raw_text or "{}")
    except Exception as e:
        manual = {"parse_error": str(e)}
    from kr_stocks import search_kr_stocks, KR_STOCKS
    ticker_in = (body_json or {}).get("ticker") or manual.get("ticker") or ""
    # kr_stocks 매핑 테스트
    mapped = KR_STOCKS.get(ticker_in)
    search_hit = search_kr_stocks(ticker_in)[:3] if ticker_in else []
    return jsonify({
        "content_type": request.content_type,
        "raw_bytes_len": len(raw_bytes),
        "raw_bytes_hex": raw_bytes.hex()[:200],
        "raw_text": raw_text[:300],
        "body_json_parsed": body_json,
        "manual_parsed": manual,
        "ticker_in": ticker_in,
        "ticker_in_len": len(ticker_in),
        "ticker_in_codepoints": [hex(ord(c)) for c in ticker_in[:20]],
        "kr_stocks_direct": mapped,
        "search_results": search_hit,
    })


@debug_bp.route("/api/debug/dart")
def dart_debug():
    """DART 연결 진단 (STOCKINTO_DEBUG=1 + 사설 IP 일 때만)."""
    if not _debug_enabled():
        return jsonify({"error": "Not Found"}), 404
    key = os.getenv("DART_API_KEY") or ""
    info = {
        "env_key_set": bool(key),
        "env_key_len": len(key),
        "env_key_prefix": key[:4] + "..." if key else "",
        "is_available": dart_client.is_available(),
    }
    try:
        m = dart_client._load_corp_map()
        info["corp_map_size"] = len(m)
        info["sample_samsung"] = m.get("005930", "NOT_FOUND")
    except Exception as e:
        info["corp_map_error"] = str(e)[:200]
    return jsonify(info)
