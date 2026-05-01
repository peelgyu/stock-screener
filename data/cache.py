"""Thread-safe in-memory TTL cache + LRU 사이즈 제한 (메모리 폭주 방지)."""
import threading
import time
from collections import OrderedDict
from functools import wraps


# 메모리 한도 — Render 무료 512MB 환경에서 안전 마진
# 종목당 캐시 평균 5~50KB라 가정 → 1500개 = 약 30~75MB
MAX_ENTRIES = 1500


class TTLCache:
    def __init__(self, default_ttl: int = 300, max_entries: int = MAX_ENTRIES):
        self._store: "OrderedDict" = OrderedDict()
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if time.time() >= expires_at:
                del self._store[key]
                self._misses += 1
                return None
            # LRU — 최근 접근을 끝으로 이동
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value, ttl: int | None = None):
        with self._lock:
            ttl = ttl if ttl is not None else self._default_ttl
            self._store[key] = (value, time.time() + ttl)
            self._store.move_to_end(key)
            # 한도 초과 시 가장 오래 안 쓰인 항목부터 제거 (LRU eviction)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
                "hit_rate": round(self._hits / total * 100, 1) if total else 0.0,
            }


cache = TTLCache()


def cached(ttl: int = 300, key_fn=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{fn.__name__}:{repr(args[0]) if args else ''}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            if result is not None:
                cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator
