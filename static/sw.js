const CACHE_NAME = 'nutrisort-v2';
const urlsToCache = [
  '/',
  '/app/static/manifest.json',
  '/app/static/icon-192.png',
  '/app/static/icon-512.png'
];

// ── Install: 핵심 자산 캐싱 ──────────────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

// ── Activate: 구버전 캐시 정리 ────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: 캐시 우선 응답 ─────────────────────────────────────────
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});

// ── Push: 백그라운드 푸시 알림 수신 (FCM 연동 대비) ───────────────
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}

  const title   = data.title || '혈당스캐너 AI 🩸';
  const options = {
    body  : data.body  || '쾌적한 혈당 방어전, 지금 식단 촬영을 시작하세요!',
    icon  : '/app/static/icon-192.png',
    badge : '/app/static/icon-192.png',
    vibrate: [200, 100, 200],
    data  : { url: data.url || '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification Click: 알림 탭 클릭 시 앱 포커스 또는 열기 ───────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
