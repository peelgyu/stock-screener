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


# 투자 시그널 화이트리스트 — 회사명 무관, 행위·이벤트 단어만 (모든 종목 동일 잣대)
INVESTMENT_KEYWORDS = [
    # 실적·재무
    "실적", "매출", "영업이익", "순이익", "어닝", "가이던스", "실적전망",
    "결산", "분기", "반기", "잠정", "흑자전환", "적자전환", "적자폭",
    # 사업 행위·계약
    "수주", "계약", "공급", "납품", "MOU", "제휴", "협력", "협약",
    "공급계약", "장기공급", "독점공급",
    # 자본 행위
    "인수", "합병", "매각", "분사", "지분", "M&A", "인수합병",
    "자사주", "배당", "증자", "감자", "증액", "주식분할", "액면분할",
    # 시장 평가
    "목표가", "투자의견", "매수의견", "매도의견", "상향", "하향",
    "신용등급", "상향조정", "하향조정",
    # 생산·투자
    "양산", "증설", "캐파", "신공장", "착공", "준공", "가동",
    "투자", "R&D", "연구개발", "신규투자", "대규모 투자",
    # 규제·법
    "규제", "소송", "과징금", "제재", "승인", "인허가", "특허",
    "특허침해", "FDA 승인", "법적분쟁",
    # 수급
    "외국인", "기관", "공매도", "매수세", "매도세", "지분율",
    # 공시
    "공시", "정정공시", "정정", "감사보고서",
    # 거버넌스
    "CEO", "대표이사", "이사회", "주총", "주주총회", "임원교체", "사임", "선임",
    # 영문 (미국 종목 한국 매체)
    "earnings", "guidance", "acquisition", "merger", "buyback",
    "dividend", "target price", "downgrade", "upgrade", "lawsuit",
    "FDA approval",
]

# 노이즈 블랙리스트 — 마케팅·CSR·연예성 (회사명 무관)
NOISE_KEYWORDS = [
    "할인", "이벤트", "체험", "체험존", "팝업스토어", "오픈", "전시",
    "축제", "콜라보", "콜라보레이션", "쇼케이스",
    "봉사", "기부", "후원", "지원사업", "캠페인", "공익", "사회공헌",
    "SNS", "유튜브", "인플루언서", "셀럽", "광고모델", "광고", "CF",
    "포토", "사진", "영상", "잡지", "패션", "메이크업",
    "어린이날", "스승의날", "어버이날", "크리스마스", "추석", "설날",
    "신메뉴", "한정판", "체험단", "기자간담회",
    "AS센터", "방문기", "탐방", "직캠",
]


def is_available() -> bool:
    return bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))


def _is_investment_relevant(title: str, description: str = "") -> bool:
    """투자/주가 관련 뉴스인지 판정.

    1) 블랙리스트(노이즈)에 매칭되면 즉시 제외 (마케팅·CSR·연예)
    2) 화이트리스트(투자 시그널) 매칭되면 통과 (실적·계약·M&A·목표가 등)
    3) 둘 다 매칭 안 되면 제외 (애매한 일반 뉴스)
    """
    if not title:
        return False
    text = f"{title} {description}"
    text_lower = text.lower()

    # 블랙리스트 우선
    for noise in NOISE_KEYWORDS:
        if noise in text or noise.lower() in text_lower:
            return False

    # 화이트리스트 매칭
    for kw in INVESTMENT_KEYWORDS:
        if kw in text or kw.lower() in text_lower:
            return True

    return False


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
    """검색어로 뉴스 fetch + 투자 관련성 필터.

    내부적으로 30건 fetch → 화이트/블랙리스트 필터 → 상위 display개 반환.
    필터 후 결과가 너무 적으면 (3건 미만) 필터 미적용 폴백.

    Args:
        query: 검색어 (회사명 권장 — 티커보다 매칭 잘됨)
        display: 필터 후 반환할 최대 개수 (기본 10)
        sort: "date"(최신순) 또는 "sim"(정확도)

    Returns:
        [{title, link, originalLink, description, pubDate, source, relevant}, ...] or None
    """
    if not is_available():
        return None
    if not query or not query.strip():
        return None

    cache_key = f"naver_news_v2:{query}:{display}:{sort}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    try:
        # 필터 후에도 충분한 결과 보장하려고 30건 fetch
        params = {
            "query": query,
            "display": 30,
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
        all_parsed = []
        for it in items:
            link = it.get("link") or it.get("originallink") or ""
            original = it.get("originallink") or link
            source = ""
            try:
                parsed = urllib.parse.urlparse(original)
                source = parsed.netloc.replace("www.", "")
            except Exception:
                pass
            title = _strip_tags(it.get("title", ""))
            desc = _strip_tags(it.get("description", ""))
            all_parsed.append({
                "title": title,
                "link": link,
                "originalLink": original,
                "description": desc,
                "pubDate": it.get("pubDate", ""),
                "source": source,
            })

        # 투자 관련성 필터
        relevant = [it for it in all_parsed if _is_investment_relevant(it["title"], it["description"])]

        # 필터 후 결과가 너무 빈약하면 (3건 미만) 원본 fallback
        # — 마이너 종목이나 뉴스가 적은 경우 대비
        if len(relevant) >= 3:
            result = relevant[:display]
        else:
            # 폴백: 블랙리스트만 적용한 결과 (화이트리스트 통과 못해도 노이즈 아니면 OK)
            non_noise = [it for it in all_parsed if not any(
                n in f"{it['title']} {it['description']}" or n.lower() in f"{it['title']} {it['description']}".lower()
                for n in NOISE_KEYWORDS
            )]
            result = non_noise[:display] if non_noise else all_parsed[:display]

        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        return None
