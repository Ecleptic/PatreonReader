/* ============================================================================
   Patreon Reader - Service Worker
   Handles offline caching and background sync
   ============================================================================ */

const CACHE_VERSION = 'v1';
const STATIC_CACHE = `patreon-reader-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `patreon-reader-dynamic-${CACHE_VERSION}`;
const OFFLINE_POSTS_CACHE = `patreon-reader-posts-${CACHE_VERSION}`;

// Static assets to cache immediately
const STATIC_ASSETS = [
    '/',
    '/static/index.html',
    '/static/styles.css',
    '/static/app.js',
    '/static/manifest.json',
    '/static/offline.html'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing service worker...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker...');
    event.waitUntil(
        caches.keys()
            .then((keys) => {
                return Promise.all(
                    keys
                        .filter((key) => key.startsWith('patreon-reader-') && 
                                        key !== STATIC_CACHE && 
                                        key !== DYNAMIC_CACHE &&
                                        key !== OFFLINE_POSTS_CACHE)
                        .map((key) => {
                            console.log('[SW] Removing old cache:', key);
                            return caches.delete(key);
                        })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);
    
    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }
    
    // API requests - network first, cache fallback for offline posts
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(handleApiRequest(request));
        return;
    }
    
    // Static assets - cache first
    event.respondWith(handleStaticRequest(request));
});

async function handleStaticRequest(request) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }
    
    try {
        const networkResponse = await fetch(request);
        
        // Cache successful responses
        if (networkResponse.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        // Return offline page for navigation requests
        if (request.mode === 'navigate') {
            const offlinePage = await caches.match('/static/offline.html');
            if (offlinePage) {
                return offlinePage;
            }
        }
        
        throw error;
    }
}

async function handleApiRequest(request) {
    const url = new URL(request.url);
    
    // Check if this is a request for a specific post that might be cached offline
    const postMatch = url.pathname.match(/\/api\/posts\/([^/]+)\/([^/]+)$/);
    
    try {
        // Try network first
        const networkResponse = await fetch(request);
        return networkResponse;
    } catch (error) {
        // Network failed - check offline cache for post content
        if (postMatch) {
            const [, creatorSlug, postId] = postMatch;
            const offlinePost = await getOfflinePost(creatorSlug, postId);
            if (offlinePost) {
                return new Response(JSON.stringify(offlinePost), {
                    headers: { 'Content-Type': 'application/json' }
                });
            }
        }
        
        // Check if we have cached creators list
        if (url.pathname === '/api/creators') {
            const offlineCreators = await getOfflineCreators();
            if (offlineCreators) {
                return new Response(JSON.stringify(offlineCreators), {
                    headers: { 'Content-Type': 'application/json' }
                });
            }
        }
        
        // Return offline error
        return new Response(JSON.stringify({ 
            error: 'offline', 
            message: 'You are offline. Only downloaded posts are available.' 
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

// IndexedDB helpers for offline posts
const DB_NAME = 'patreon-reader-offline';
const DB_VERSION = 1;

function openDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            
            // Store for offline posts
            if (!db.objectStoreNames.contains('posts')) {
                const postsStore = db.createObjectStore('posts', { keyPath: ['creator_slug', 'id'] });
                postsStore.createIndex('creator', 'creator_slug', { unique: false });
                postsStore.createIndex('downloaded_at', 'downloaded_at', { unique: false });
            }
            
            // Store for creators (for offline list)
            if (!db.objectStoreNames.contains('creators')) {
                db.createObjectStore('creators', { keyPath: 'slug' });
            }
        };
    });
}

async function getOfflinePost(creatorSlug, postId) {
    try {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction('posts', 'readonly');
            const store = tx.objectStore('posts');
            const request = store.get([creatorSlug, postId]);
            
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('[SW] Error getting offline post:', error);
        return null;
    }
}

async function getOfflineCreators() {
    try {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction('creators', 'readonly');
            const store = tx.objectStore('creators');
            const request = store.getAll();
            
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('[SW] Error getting offline creators:', error);
        return null;
    }
}

// Message handler for communication with main app
self.addEventListener('message', (event) => {
    const { type, data } = event.data;
    
    switch (type) {
        case 'SKIP_WAITING':
            self.skipWaiting();
            break;
            
        case 'CACHE_POST':
            // Handled by main thread using IndexedDB directly
            break;
            
        case 'CLEAR_CACHE':
            clearAllCaches().then(() => {
                event.ports[0].postMessage({ success: true });
            });
            break;
    }
});

async function clearAllCaches() {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key)));
}
