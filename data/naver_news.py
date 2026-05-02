"""네이버 뉴스 검색 API — 종목별 관련 뉴스.

근거: 네이버 개발자센터 검색 API (https://developers.naver.com/docs/serviceapi/search/news/news.md)
인증: NAVER_CLIENT_ID + NAVER_CLIENT_SECRET 환경변수 (개발자센터에서 발급)
호출 한도: 일 25,000건 (무료, 상업 이용 OK)
저작권: 제목·요약·링크만 노출 → 원문 트래픽은 언론사로 송신 (링크 어그리게이션 합법)

캐시: 종목당 6시간 (뉴스는 빨리 식음)
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from typing import Optional

from .cache import cache


_API_URL = "https://openapi.naver.com/v1/search/news.json"
_CACHE_TTL = 6 * 3600  # 6h — 뉴스는 자주 갱신


def is_available() -> bool:
    return bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))


def _strip_tags(s: str) -> str:
    """네이버 응답에 들어있는 <b>...</b> 강조 태그 + HTML 엔티티 제거."""
    if not s:
        return ""
    # <b>·</b> 등 태그 제거
    s = re.sub(r"<[^>]+>", "", s)
    # 엔티티 디코딩 (간단)
    s = (s.replace("&quot;", '"')
           .replace("&amp;", "&")
           .replace("&lt;", "<")
           .replace("&gt;", ">")
           .replace("&apos;", "'")
           .replace("&#39;", "'"))
    return s.strip()


def fetch_news(query: str, display: int = 10, sort: str = "date") -> Optional[list]:
    """검색어로 뉴스 fetch.

    Args:
        query: 검색어 (회사명 권장 — 티커보다 매칭 잘됨)
        display: 결과 개수 (1~100, 기본 10)
        sort: "date"(최신순) 또는 "sim"(정확도)

    Returns:
        [{title, link, originalLink, description, pubDate, source}, ...] or None
    """
    if not is_available():
        return None
    if not query or not query.strip():
        return None

    cache_key = f"naver_news:{query}:{display}:{sort}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    try:
        params = {
            "query": query,
            "display": min(max(int(display), 1), 100),
            "sort": sort,
        }
        url = f"{_API_URL}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", os.getenv("NAVER_CLIENT_ID", ""))
        req.add_header("X-Naver-Client-Secret", os.getenv("NAVER_CLIENT_SECRET", ""))

        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items") or []
        result = []
        for it in items:
            link = it.get("link") or it.get("originallink") or ""
            original = it.get("originallink") or link
            # 출처 도메인 추출 (예: https://news.mt.co.kr/... → news.mt.co.kr)
            source = ""
            try:
                parsed = urllib.parse.urlparse(original)
                source = parsed.netloc.replace("www.", "")
            except Exception:
                pass
            result.append({
                "title": _strip_tags(it.get("title", "")),
                "link": link,  # 네이버 뉴스 링크 (있으면) — UX 좋음
                "originalLink": original,  # 언론사 원본
                "description": _strip_tags(it.get("description", "")),
                "pubDate": it.get("pubDate", ""),  # RFC822 형식
                "source": source,
            })

        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return None
