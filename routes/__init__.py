"""Flask Blueprint 모음 — app.py 모놀리스 분리 (작업 순서: cron→debug→pages→api_market→api_stock).

각 Blueprint는 독립 모듈로, 자체 라우트만 등록.
공통 헬퍼는 import해서 사용 (필요하면 routes/_shared.py 추가).
"""
from .cron import cron_bp
from .debug import debug_bp
from .api_market import api_market_bp
from .pages import pages_bp

__all__ = ["cron_bp", "debug_bp", "api_market_bp", "pages_bp"]
