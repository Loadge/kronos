/*
 * Kronos service worker — the app shell is network-first, static assets are
 * stale-while-revalidate. API calls (/api/*) are always network-only; never cached.
 *
 * `__BUILD__` is filled in by the server (GET /sw.js) with the build id: a hash of
 * every file the browser loads. A deploy that changes any of them gives this worker a new
 * cache name, so the browser installs it, the old cache is pruned, and nobody has to
 * remember to bump anything. The page's own check (the "Update ready" pill) covers the
 * rest: it tells an open tab that the server has a newer build.
 */

const CACHE_NAME = 'kronos-__BUILD__';

/** Assets to pre-cache on install so the app shell is available offline. The two files that
 *  change with every build are linked with their build id (`?v=`), exactly as index.html does. */
const PRECACHE_URLS = [
  '/',
  '/manifest.json',
  '/static/styles.css?v=__BUILD__',
  '/static/app.js?v=__BUILD__',
  '/static/dial.js?v=__BUILD__',
  '/static/icon.png',
  '/static/vendor/pico.min.css',
  '/static/vendor/alpine.min.js',
];

// ── Install: fill the cache ─────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())  // activate immediately, don't wait for old SW to die
  );
});

// ── Activate: prune stale caches ────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())  // take control of all open tabs immediately
  );
});

// ── Fetch: network-first for the shell; stale-while-revalidate for static; network-only for API ──
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only intercept same-origin GETs
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // API, exports, healthz, and the timesheet (a report must never be stale) → always
  // go to network; never cache
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz' || url.pathname === '/timesheet') return;

  // The page itself: the network decides, so a reload shows the newest version.
  // The cache is only for being offline.
  if (request.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(networkFirst(request));
    return;
  }

  // Everything else is safe to serve from the cache first: styles.css and app.js are linked
  // with the build id, so a new build asks for new URLs.
  event.respondWith(staleWhileRevalidate(request));
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    throw err;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  // Kick off a background network fetch regardless
  const networkPromise = fetch(request)
    .then(response => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // Return cached version immediately if available; otherwise wait for network
  return cached ?? await networkPromise;
}
