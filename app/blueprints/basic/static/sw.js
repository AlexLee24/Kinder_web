// Kinder service worker (2026-10): makes "Add to Home Screen" behave like an app and makes repeat
// visits on a phone fast. Served from /sw.js (app/core/static_files.py) so its scope is the whole site.
//
// What is cached — only things whose URL changes when their content changes, so nothing goes stale:
//   · /static/...?v=<mtime>   url_for('static') adds the version; cache-first, old versions dropped.
//   · Google Fonts, cdn.plot.ly / jsdelivr / jQuery / Aladin libraries: stale-while-revalidate
//     (instant from cache, refreshed in the background — Plotly alone is ~3.5 MB on a phone).
// What is never cached:
//   · Pages (HTML): always from the network — they depend on who is logged in and on live data.
//     Only when the network fails is the pre-cached /offline page shown.
//   · /api/..., POSTs, uploads, anything without ?v=: untouched, the browser behaves as without a worker.
const VERSION = 'kinder-2026-10-03a';
const SHELL = VERSION + '-shell';
const STATIC = 'kinder-static-v1';     // not tied to VERSION: a new worker doesn't re-download every file
const IMAGES = 'kinder-img-v1';
const LIBS = 'kinder-libs-v1';
const STATIC_MAX = 300;
const IMAGES_MAX = 60;
const IMAGE_MAX_BYTES = 6 * 1024 * 1024;
const OFFLINE_URL = '/offline';
const SHELL_FILES = [OFFLINE_URL, '/static/pwa/logo-128.png', '/static/pwa/icon-192.png'];
const LIB_HOSTS = new Set(['cdn.plot.ly', 'cdn.jsdelivr.net', 'code.jquery.com', 'aladin.cds.unistra.fr',
                           'fonts.googleapis.com', 'fonts.gstatic.com']);

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keep = new Set([SHELL, STATIC, IMAGES, LIBS]);
        for (const k of await caches.keys()) if (!keep.has(k)) await caches.delete(k);
        if (self.registration.navigationPreload) { try { await self.registration.navigationPreload.enable(); } catch (e) {} }
        await self.clients.claim();
    })());
});

function isImage(path) { return /\.(png|jpe?g|webp|gif|svg|ico)$/i.test(path); }

async function trim(cacheName, max) {
    const c = await caches.open(cacheName);
    const keys = await c.keys();
    for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);   // oldest first
}

// Keep one copy per file: drop older versions (same path, different ?v=)
async function dropOlder(cache, url) {
    for (const k of await cache.keys()) {
        const u = new URL(k.url);
        if (u.pathname === url.pathname && u.search !== url.search) await cache.delete(k);
    }
}

async function cacheFirst(event, url) {
    const name = isImage(url.pathname) ? IMAGES : STATIC;
    const cache = await caches.open(name);
    const hit = await cache.match(event.request);
    if (hit) return hit;
    const resp = await fetch(event.request);
    if (resp.ok && resp.type === 'basic') {
        const len = Number(resp.headers.get('content-length') || 0);
        if (!(name === IMAGES && len > IMAGE_MAX_BYTES)) {
            const copy = resp.clone();
            event.waitUntil((async () => {
                await dropOlder(cache, url);
                await cache.put(event.request, copy);
                await trim(name, name === IMAGES ? IMAGES_MAX : STATIC_MAX);
            })());
        }
    }
    return resp;
}

async function staleWhileRevalidate(event) {
    const cache = await caches.open(LIBS);
    const hit = await cache.match(event.request);
    const net = fetch(event.request).then((r) => {
        if (r.ok || r.type === 'opaque') event.waitUntil(cache.put(event.request, r.clone()));
        return r;
    }).catch(() => hit || Response.error());
    if (hit) { event.waitUntil(net.catch(() => {})); return hit; }
    return net;
}

async function navigate(event) {
    try {
        const pre = await event.preloadResponse;
        if (pre) return pre;
        return await fetch(event.request);
    } catch (e) {
        const off = await caches.match(OFFLINE_URL);
        return off || new Response('<h1>Offline</h1><p>No network connection.</p>', { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }
}

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) {
        if (LIB_HOSTS.has(url.hostname)) event.respondWith(staleWhileRevalidate(event));
        return;
    }
    if (req.mode === 'navigate') {
        event.respondWith(navigate(event));
        return;
    }
    if (SHELL_FILES.includes(url.pathname)) {
        event.respondWith(fetch(req).catch(() => caches.match(url.pathname).then((r) => r || Response.error())));
        return;
    }
    if (url.pathname.startsWith('/static/') && url.searchParams.has('v')) {
        event.respondWith(cacheFirst(event, url).catch(() => caches.match(req).then((r) => r || Response.error())));
    }
    // everything else (/api, /object data, un-versioned files): not intercepted
});
