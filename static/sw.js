// StockInto Service Worker - v55 (🛡 CSP 4차 — 잔여 인라인 style 87건 제거 완료)
// 메인 HTML은 캐시 안 함 (항상 최신 JS/CSS 받도록)
const CACHE_NAME = 'stockinto-v55';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // API 요청은 네트워크 우선, 실패 시 에러
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: '오프라인 상태입니다' }),
        { headers: { 'Content-Type': 'application/json' }, status: 503 }
      ))
    );
    return;
  }

  // 메인 HTML 페이지(/, /install, /terms, /privacy)는 항상 네트워크에서 받기
  // (캐시하지 않음 → 업데이트 즉시 반영)
  if (req.destination === 'document') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/static/manifest.json'))
    );
    return;
  }

  // JS·CSS는 네트워크 우선 (배포 즉시 반영 — cache-first면 옛 버전 영원히 잡혀 있는 버그)
  // 네트워크 실패 시에만 캐시 폴백 (오프라인 안정성)
  if (url.pathname.endsWith('.js') || url.pathname.endsWith('.css')) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok && res.type === 'basic') {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, resClone));
        }
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 진짜 정적 자원(이미지·아이콘·폰트)만 캐시 우선
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        if (res.ok && res.type === 'basic') {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, resClone));
        }
        return res;
      });
    })
  );
});
