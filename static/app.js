/* ============================================================================
   Patreon Reader - JavaScript App
   ============================================================================ */

// API base URL - loaded from config endpoint, defaults to same origin
let API_BASE = '';

// App state
const state = {
    currentView: 'creators',
    currentCreator: null,
    currentPost: null,
    creators: [],
    posts: [],
    postsOffset: 0,
    postsLimit: 50,
    syncRunning: false,
    searchTimeout: null,
    prevPostId: null,
    nextPostId: null,
    authRequired: false,
    authenticated: false,
    isOnline: navigator.onLine,
    offlineDb: null,
    configLoaded: false
};

// View history for back navigation
const viewHistory = [];

/* ============================================================================
   Configuration
   ============================================================================ */

async function loadConfig() {
    try {
        // Try to load config from the API
        const response = await fetch('/api/config');
        if (response.ok) {
            const config = await response.json();
            API_BASE = config.api_url || '';
            state.authRequired = config.auth_enabled;
            state.configLoaded = true;
            console.log('Config loaded:', { api_url: API_BASE, auth_enabled: config.auth_enabled });
            return config;
        }
    } catch (error) {
        console.warn('Failed to load config, using defaults:', error);
    }
    
    // Fallback to same-origin
    API_BASE = '';
    state.configLoaded = true;
    return { api_url: '', auth_enabled: false };
}

/* ============================================================================
   Service Worker & PWA
   ============================================================================ */

async function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        try {
            const registration = await navigator.serviceWorker.register('/sw.js');
            console.log('Service Worker registered:', registration.scope);
            
            // Check for updates
            registration.addEventListener('updatefound', () => {
                const newWorker = registration.installing;
                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        // New version available
                        showToast('New version available. Refresh to update.', 'info');
                    }
                });
            });
        } catch (error) {
            console.error('Service Worker registration failed:', error);
        }
    }
}

// Online/offline detection
window.addEventListener('online', () => {
    state.isOnline = true;
    showToast('Back online', 'success');
    document.body.classList.remove('offline-mode');
});

window.addEventListener('offline', () => {
    state.isOnline = false;
    showToast('You are offline. Only downloaded posts available.', 'warning');
    document.body.classList.add('offline-mode');
});

/* ============================================================================
   Offline Storage (IndexedDB)
   ============================================================================ */

const DB_NAME = 'patreon-reader-offline';
const DB_VERSION = 1;

async function initOfflineDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            state.offlineDb = request.result;
            resolve(request.result);
        };
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            
            if (!db.objectStoreNames.contains('posts')) {
                const postsStore = db.createObjectStore('posts', { keyPath: ['creator_slug', 'id'] });
                postsStore.createIndex('creator', 'creator_slug', { unique: false });
                postsStore.createIndex('downloaded_at', 'downloaded_at', { unique: false });
            }
            
            if (!db.objectStoreNames.contains('creators')) {
                db.createObjectStore('creators', { keyPath: 'slug' });
            }
        };
    });
}

async function savePostOffline(post) {
    if (!state.offlineDb) return false;
    
    return new Promise((resolve, reject) => {
        const tx = state.offlineDb.transaction('posts', 'readwrite');
        const store = tx.objectStore('posts');
        
        const offlinePost = {
            ...post,
            downloaded_at: new Date().toISOString()
        };
        
        const request = store.put(offlinePost);
        request.onsuccess = () => resolve(true);
        request.onerror = () => reject(request.error);
    });
}

async function removePostOffline(creatorSlug, postId) {
    if (!state.offlineDb) return false;
    
    return new Promise((resolve, reject) => {
        const tx = state.offlineDb.transaction('posts', 'readwrite');
        const store = tx.objectStore('posts');
        const request = store.delete([creatorSlug, postId]);
        
        request.onsuccess = () => resolve(true);
        request.onerror = () => reject(request.error);
    });
}

async function getOfflinePost(creatorSlug, postId) {
    if (!state.offlineDb) return null;
    
    return new Promise((resolve, reject) => {
        const tx = state.offlineDb.transaction('posts', 'readonly');
        const store = tx.objectStore('posts');
        const request = store.get([creatorSlug, postId]);
        
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function getOfflinePostsByCreator(creatorSlug) {
    if (!state.offlineDb) return [];
    
    return new Promise((resolve, reject) => {
        const tx = state.offlineDb.transaction('posts', 'readonly');
        const store = tx.objectStore('posts');
        const index = store.index('creator');
        const request = index.getAll(creatorSlug);
        
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
    });
}

async function getAllOfflinePosts() {
    if (!state.offlineDb) return [];
    
    return new Promise((resolve, reject) => {
        const tx = state.offlineDb.transaction('posts', 'readonly');
        const store = tx.objectStore('posts');
        const request = store.getAll();
        
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
    });
}

async function isPostOffline(creatorSlug, postId) {
    const post = await getOfflinePost(creatorSlug, postId);
    return post !== null && post !== undefined;
}

async function getOfflineCount() {
    const posts = await getAllOfflinePosts();
    return posts.length;
}

/* ============================================================================
   Authentication
   ============================================================================ */

function getStoredToken() {
    return localStorage.getItem('patreon_reader_token');
}

function setStoredToken(token) {
    if (token) {
        localStorage.setItem('patreon_reader_token', token);
    } else {
        localStorage.removeItem('patreon_reader_token');
    }
}

async function checkAuth() {
    // First check if auth is required
    try {
        const health = await fetch(`${API_BASE}/api/health`).then(r => r.json());
        state.authRequired = health.auth_enabled;
        
        if (!state.authRequired) {
            state.authenticated = true;
            return true;
        }
        
        // Auth is required, check if we have a valid token
        const token = getStoredToken();
        if (!token) {
            return false;
        }
        
        const response = await fetch(`${API_BASE}/api/auth/check`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (response.ok) {
            state.authenticated = true;
            return true;
        } else {
            setStoredToken(null);
            return false;
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        return false;
    }
}

function showLoginScreen() {
    document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('app-content').classList.add('hidden');
    document.getElementById('login-token').focus();
}

function hideLoginScreen() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app-content').classList.remove('hidden');
}

async function attemptLogin() {
    const tokenInput = document.getElementById('login-token');
    const token = tokenInput.value.trim();
    
    if (!token) {
        showToast('Please enter a token', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/check`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (response.ok) {
            setStoredToken(token);
            state.authenticated = true;
            hideLoginScreen();
            loadCreators();
            showToast('Logged in successfully', 'success');
        } else {
            showToast('Invalid token', 'error');
        }
    } catch (error) {
        showToast('Login failed', 'error');
    }
}

function logout() {
    setStoredToken(null);
    state.authenticated = false;
    state.creators = [];
    state.posts = [];
    showLoginScreen();
    showToast('Logged out', 'success');
}

/* ============================================================================
   API Helpers
   ============================================================================ */

async function api(endpoint, options = {}) {
    try {
        const token = getStoredToken();
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers,
            ...options
        });
        
        if (response.status === 401) {
            // Token expired or invalid
            if (state.authRequired) {
                setStoredToken(null);
                state.authenticated = false;
                showLoginScreen();
                throw new Error('Session expired. Please log in again.');
            }
        }
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        showToast(error.message, 'error');
        throw error;
    }
}

/* ============================================================================
   Navigation
   ============================================================================ */

function showView(viewName, pushHistory = true) {
    // Hide all views
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    
    // Show target view
    const view = document.getElementById(`view-${viewName}`);
    if (view) {
        view.classList.add('active');
    }
    
    // Update navigation
    const backBtn = document.getElementById('nav-back');
    const title = document.getElementById('nav-title');
    
    if (viewName === 'creators') {
        backBtn.classList.add('hidden');
        title.textContent = 'Patreon Reader';
    } else {
        backBtn.classList.remove('hidden');
    }
    
    // Update title based on view
    if (viewName === 'posts' && state.currentCreator) {
        title.textContent = state.currentCreator.name;
    } else if (viewName === 'reader' && state.currentPost) {
        title.textContent = state.currentPost.title;
    } else if (viewName === 'settings') {
        title.textContent = 'Settings';
    }
    
    // Push to history
    if (pushHistory && state.currentView !== viewName) {
        viewHistory.push(state.currentView);
    }
    
    state.currentView = viewName;
}

function goBack() {
    // Stop reading position tracking when leaving reader
    stopReadingPositionTracking();
    
    if (viewHistory.length > 0) {
        const prevView = viewHistory.pop();
        showView(prevView, false);
        // Re-render posts list to update read/unread status
        if (prevView === 'posts') {
            renderPosts();
        }
    } else {
        showView('creators', false);
    }
}

/* ============================================================================
   Creators
   ============================================================================ */

async function loadCreators() {
    try {
        state.creators = await api('/api/creators');
        renderCreators();
    } catch (error) {
        console.error('Failed to load creators:', error);
    }
}

function renderCreators() {
    const list = document.getElementById('creators-list');
    
    if (state.creators.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 4v16m-8-8h16"/>
                </svg>
                <h3>No Creators Yet</h3>
                <p>Add a Patreon creator to get started</p>
            </div>
        `;
        return;
    }
    
    const searchTerm = document.getElementById('creator-search').value.toLowerCase();
    const filtered = state.creators.filter(c => 
        c.name.toLowerCase().includes(searchTerm) || 
        c.slug.toLowerCase().includes(searchTerm)
    );
    
    list.innerHTML = filtered.map(creator => {
        const unreadBadge = creator.unread_count > 0 
            ? `<span class="item-badge unread">${creator.unread_count} unread</span>` 
            : '';
        return `
        <div class="list-item" onclick="selectCreator('${creator.slug}')">
            <div class="item-title">
                ${escapeHtml(creator.name)}
                <span class="item-badge">${creator.post_count}</span>
                ${unreadBadge}
            </div>
            <div class="item-meta">
                ${creator.latest_post ? `Latest: ${formatDate(creator.latest_post)}` : 'No posts yet'}
            </div>
        </div>
    `}).join('');
}

function filterCreators() {
    renderCreators();
}

async function selectCreator(slug) {
    state.currentCreator = state.creators.find(c => c.slug === slug);
    state.posts = [];
    state.postsOffset = 0;
    
    showView('posts');
    await loadPosts();
}

/* ============================================================================
   Posts
   ============================================================================ */

async function loadPosts(append = false) {
    if (!state.currentCreator) return;
    
    try {
        const searchTerm = document.getElementById('post-search').value;
        let endpoint = `/api/posts/${state.currentCreator.slug}?limit=${state.postsLimit}&offset=${state.postsOffset}`;
        
        if (searchTerm) {
            endpoint += `&search=${encodeURIComponent(searchTerm)}`;
        }
        
        const posts = await api(endpoint);
        
        if (append) {
            state.posts = [...state.posts, ...posts];
        } else {
            state.posts = posts;
        }
        
        renderPosts();
    } catch (error) {
        console.error('Failed to load posts:', error);
    }
}

function renderPosts() {
    const list = document.getElementById('posts-list');
    
    if (state.posts.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <h3>No Posts</h3>
                <p>Run a sync to download posts</p>
            </div>
        `;
        return;
    }
    
    list.innerHTML = state.posts.map(post => {
        const readClass = post.is_read ? 'is-read' : 'unread';
        return `
        <div class="list-item ${readClass}" onclick="selectPost('${escapeHtml(post.id)}')">
            <div class="item-title">${escapeHtml(post.title)}</div>
            <div class="item-meta">${post.published_date ? formatDate(post.published_date) : ''}</div>
        </div>
    `}).join('');
}

function searchPosts() {
    // Debounce search
    clearTimeout(state.searchTimeout);
    state.searchTimeout = setTimeout(() => {
        state.postsOffset = 0;
        loadPosts();
    }, 300);
}

async function selectPost(postId) {
    if (!state.currentCreator) return;
    
    try {
        let post;
        
        // Try to get post from API first, fallback to offline
        try {
            post = await api(`/api/posts/${state.currentCreator.slug}/${encodeURIComponent(postId)}`);
        } catch (error) {
            // If offline or API error, try to get from offline storage
            post = await getOfflinePost(state.currentCreator.slug, postId);
            if (!post) {
                showToast('Post not available offline', 'error');
                return;
            }
            showToast('Reading from offline storage', 'info');
        }
        
        state.currentPost = post;
        
        // Render post
        document.getElementById('reader-title').textContent = post.title;
        document.getElementById('reader-meta').innerHTML = `
            ${post.published_date ? formatDate(post.published_date) : ''}
            ${post.url ? ` • <a href="${post.url}" target="_blank">View on Patreon</a>` : ''}
        `;
        document.getElementById('reader-body').innerHTML = post.content || '<p>No content</p>';
        
        // Update read status button
        updateReadStatusUI(post.is_read);
        
        // Update navigation buttons
        updateNavButtons(post.prev_post_id, post.next_post_id);
        
        // Update offline download button
        await updateOfflineUI(state.currentCreator.slug, postId);
        
        // Mark as read in local posts list too
        const postInList = state.posts.find(p => p.id === postId);
        if (postInList) postInList.is_read = true;
        
        showView('reader');
        
        // Restore reading position or scroll to top
        const savedPosition = getReadingPosition(postId);
        const readerView = document.getElementById('view-reader');
        
        if (savedPosition) {
            // Wait for content to render, then scroll to saved paragraph
            setTimeout(() => {
                scrollToElementIndex(savedPosition.elementIndex, savedPosition.scrollOffset);
            }, 100);
        } else {
            readerView.scrollTop = 0;
        }
        
        // Start tracking reading position
        startReadingPositionTracking(postId);
    } catch (error) {
        console.error('Failed to load post:', error);
    }
}

async function updateOfflineUI(creatorSlug, postId) {
    const btn = document.getElementById('offline-toggle-btn');
    const icon = document.getElementById('offline-status-icon');
    const text = document.getElementById('offline-status-text');
    
    if (!btn) return;
    
    const isOffline = await isPostOffline(creatorSlug, postId);
    
    if (isOffline) {
        btn.classList.add('is-offline');
        icon.textContent = '✓';
        text.textContent = 'Saved';
    } else {
        btn.classList.remove('is-offline');
        icon.textContent = '↓';
        text.textContent = 'Save';
    }
}

async function toggleOfflinePost() {
    if (!state.currentPost || !state.currentCreator) return;
    
    const creatorSlug = state.currentCreator.slug;
    const postId = state.currentPost.id;
    const isOffline = await isPostOffline(creatorSlug, postId);
    
    try {
        if (isOffline) {
            await removePostOffline(creatorSlug, postId);
            showToast('Removed from offline storage', 'success');
        } else {
            await savePostOffline(state.currentPost);
            showToast('Saved for offline reading', 'success');
        }
        
        await updateOfflineUI(creatorSlug, postId);
    } catch (error) {
        console.error('Failed to toggle offline status:', error);
        showToast('Failed to update offline storage', 'error');
    }
}

function updateReadStatusUI(isRead) {
    const btn = document.getElementById('read-toggle-btn');
    const icon = document.getElementById('read-status-icon');
    const text = document.getElementById('read-status-text');
    
    if (isRead) {
        btn.classList.add('is-read');
        icon.textContent = '✓';
        text.textContent = 'Read';
    } else {
        btn.classList.remove('is-read');
        icon.textContent = '○';
        text.textContent = 'Mark Read';
    }
}

function updateNavButtons(prevId, nextId) {
    const prevBtnTop = document.getElementById('prev-btn-top');
    const prevBtnBottom = document.getElementById('prev-btn-bottom');
    const nextBtnTop = document.getElementById('next-btn-top');
    const nextBtnBottom = document.getElementById('next-btn-bottom');
    
    prevBtnTop.disabled = !prevId;
    prevBtnBottom.disabled = !prevId;
    nextBtnTop.disabled = !nextId;
    nextBtnBottom.disabled = !nextId;
    
    state.prevPostId = prevId;
    state.nextPostId = nextId;
}

/* ============================================================================
   Reading Position Tracking
   ============================================================================ */

let readingPositionTimer = null;

function getReadingPositionKey(postId) {
    return `reading_position_${postId}`;
}

function getReadingPosition(postId) {
    const key = getReadingPositionKey(postId);
    const saved = localStorage.getItem(key);
    if (saved) {
        try {
            return JSON.parse(saved);
        } catch (e) {
            return null;
        }
    }
    return null;
}

function saveReadingPosition(postId, elementIndex, scrollOffset) {
    const key = getReadingPositionKey(postId);
    localStorage.setItem(key, JSON.stringify({
        elementIndex,
        scrollOffset,
        savedAt: Date.now()
    }));
}

function clearReadingPosition(postId) {
    const key = getReadingPositionKey(postId);
    localStorage.removeItem(key);
}

function getVisibleElementIndex() {
    const readerBody = document.getElementById('reader-body');
    const readerView = document.getElementById('view-reader');
    
    if (!readerBody) return { elementIndex: 0, scrollOffset: 0 };
    
    // Get all block-level elements (paragraphs, divs, headings, etc.)
    const elements = readerBody.querySelectorAll('p, div, h1, h2, h3, h4, h5, h6, li, blockquote');
    const viewportTop = readerView.scrollTop + 100; // Account for nav bar
    
    for (let i = 0; i < elements.length; i++) {
        const elem = elements[i];
        const rect = elem.getBoundingClientRect();
        const elemTop = rect.top + readerView.scrollTop;
        
        if (elemTop >= viewportTop - 50) {
            // This element is at or near the top of the viewport
            return {
                elementIndex: i,
                scrollOffset: viewportTop - elemTop
            };
        }
    }
    
    // Return last element if we scrolled past everything
    return {
        elementIndex: Math.max(0, elements.length - 1),
        scrollOffset: 0
    };
}

function scrollToElementIndex(elementIndex, scrollOffset = 0) {
    const readerBody = document.getElementById('reader-body');
    const readerView = document.getElementById('view-reader');
    
    if (!readerBody) return;
    
    const elements = readerBody.querySelectorAll('p, div, h1, h2, h3, h4, h5, h6, li, blockquote');
    
    if (elementIndex >= 0 && elementIndex < elements.length) {
        const elem = elements[elementIndex];
        const rect = elem.getBoundingClientRect();
        const elemTop = rect.top + readerView.scrollTop - 100; // Account for nav bar
        readerView.scrollTop = elemTop + scrollOffset;
    }
}

function startReadingPositionTracking(postId) {
    // Stop any existing tracking
    stopReadingPositionTracking();
    
    // Save position every 2 seconds while reading
    readingPositionTimer = setInterval(() => {
        if (state.currentPost && state.currentPost.id === postId) {
            const position = getVisibleElementIndex();
            saveReadingPosition(postId, position.elementIndex, position.scrollOffset);
        }
    }, 2000);
}

function stopReadingPositionTracking() {
    if (readingPositionTimer) {
        clearInterval(readingPositionTimer);
        readingPositionTimer = null;
    }
}

async function goToPrevPost() {
    stopReadingPositionTracking();
    if (state.prevPostId) {
        await selectPost(state.prevPostId);
    }
}

async function goToNextPost() {
    stopReadingPositionTracking();
    if (state.nextPostId) {
        await selectPost(state.nextPostId);
    }
}

async function toggleReadStatus() {
    if (!state.currentPost || !state.currentCreator) return;
    
    const newStatus = !state.currentPost.is_read;
    
    try {
        await api(`/api/posts/${state.currentCreator.slug}/${encodeURIComponent(state.currentPost.id)}/read?is_read=${newStatus}`, {
            method: 'PUT'
        });
        
        state.currentPost.is_read = newStatus;
        updateReadStatusUI(newStatus);
        
        // Update in posts list too
        const postInList = state.posts.find(p => p.id === state.currentPost.id);
        if (postInList) postInList.is_read = newStatus;
        
        showToast(newStatus ? 'Marked as read' : 'Marked as unread', 'success');
    } catch (error) {
        console.error('Failed to update read status:', error);
    }
}

/* ============================================================================
   Add Creator
   ============================================================================ */

function showAddCreator() {
    document.getElementById('modal-add-creator').classList.remove('hidden');
    document.getElementById('new-creator-url').focus();
}

function hideModal() {
    document.getElementById('modal-add-creator').classList.add('hidden');
    document.getElementById('new-creator-url').value = '';
    document.getElementById('new-creator-name').value = '';
}

async function addCreator() {
    const url = document.getElementById('new-creator-url').value.trim();
    const name = document.getElementById('new-creator-name').value.trim();
    
    if (!url) {
        showToast('Please enter a Patreon URL', 'error');
        return;
    }
    
    try {
        const result = await api('/api/creators', {
            method: 'POST',
            body: JSON.stringify({ url, name: name || undefined })
        });
        
        hideModal();
        showToast(`Added ${result.name}! Starting sync...`, 'success');
        await loadCreators();
        
        // Start polling for sync progress
        startSyncProgressPolling();
    } catch (error) {
        console.error('Failed to add creator:', error);
    }
}

/* ============================================================================
   Sync
   ============================================================================ */

let syncPollInterval = null;

function showSyncMenu() {
    showView('settings');
    loadSyncStatus();
    loadSyncProgress();
    updateAuthUI();
    updateOfflineStats();
}

function updateAuthUI() {
    const authSection = document.getElementById('auth-section');
    const authStatus = document.getElementById('auth-status-text');
    
    if (state.authRequired) {
        authSection.style.display = 'block';
        authStatus.textContent = 'Logged in with API token';
    } else {
        authSection.style.display = 'none';
    }
}

async function updateOfflineStats() {
    const offlineStats = document.getElementById('offline-stats');
    try {
        const count = await getOfflineCount();
        const posts = await getAllOfflinePosts();
        
        // Calculate storage size (rough estimate)
        const storageSize = JSON.stringify(posts).length;
        const sizeStr = storageSize > 1024 * 1024 
            ? `${(storageSize / 1024 / 1024).toFixed(1)} MB`
            : `${(storageSize / 1024).toFixed(1)} KB`;
        
        offlineStats.textContent = `${count} posts saved (${sizeStr})`;
    } catch (error) {
        offlineStats.textContent = 'Unable to load offline stats';
    }
}

async function viewOfflinePosts() {
    try {
        const posts = await getAllOfflinePosts();
        
        if (posts.length === 0) {
            showToast('No offline posts saved', 'info');
            return;
        }
        
        // Show offline posts as a list
        state.posts = posts.map(p => ({
            id: p.id,
            title: p.title,
            published_date: p.published_date,
            creator_slug: p.creator_slug,
            is_read: p.is_read || false,
            is_offline: true
        }));
        
        state.currentCreator = { slug: '_offline', name: 'Offline Posts' };
        showView('posts');
        renderPosts();
        
        // Update nav title
        document.getElementById('nav-title').textContent = 'Offline Posts';
    } catch (error) {
        console.error('Failed to load offline posts:', error);
        showToast('Failed to load offline posts', 'error');
    }
}

async function clearOfflinePosts() {
    if (!confirm('Remove all saved offline posts?')) return;
    
    try {
        if (state.offlineDb) {
            const tx = state.offlineDb.transaction('posts', 'readwrite');
            const store = tx.objectStore('posts');
            await new Promise((resolve, reject) => {
                const request = store.clear();
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }
        
        showToast('Offline posts cleared', 'success');
        updateOfflineStats();
    } catch (error) {
        console.error('Failed to clear offline posts:', error);
        showToast('Failed to clear offline posts', 'error');
    }
}

async function loadSyncStatus() {
    try {
        const status = await api('/api/sync/status');
        
        document.getElementById('sync-status').innerHTML = `
            <p>Auto sync: <span class="${status.running ? 'status-running' : 'status-stopped'}">
                ${status.running ? '● Running' : '○ Off'}
            </span></p>
        `;
        
        document.getElementById('sync-interval').value = status.interval_hours;
        document.getElementById('bg-sync-toggle').textContent = 
            status.running ? 'Stop Auto Sync' : 'Start Auto Sync';
        document.getElementById('bg-sync-toggle').className = 
            status.running ? 'btn btn-secondary' : 'btn';
        
        document.getElementById('stats').innerHTML = `
            <p>Creators: ${status.total_creators}</p>
            <p>Total Posts: ${status.total_posts}</p>
        `;
        
        state.syncRunning = status.running;
    } catch (error) {
        console.error('Failed to load sync status:', error);
    }
}

async function loadSyncProgress() {
    try {
        const progress = await api('/api/sync/progress');
        const progressEl = document.getElementById('sync-progress');
        const quickBtn = document.getElementById('btn-quick-sync');
        const fullBtn = document.getElementById('btn-full-sync');
        
        if (progress.in_progress) {
            progressEl.classList.remove('hidden');
            progressEl.innerHTML = `
                <div class="sync-indicator">
                    <span class="spinner"></span>
                    <span>${progress.message || 'Syncing...'}</span>
                </div>
            `;
            quickBtn.disabled = true;
            fullBtn.disabled = true;
        } else {
            if (progress.message && progress.message !== '') {
                progressEl.classList.remove('hidden');
                progressEl.innerHTML = `<div class="sync-complete">${progress.message}</div>`;
            } else {
                progressEl.classList.add('hidden');
            }
            quickBtn.disabled = false;
            fullBtn.disabled = false;
        }
        
        return progress.in_progress;
    } catch (error) {
        console.error('Failed to load sync progress:', error);
        return false;
    }
}

function startSyncProgressPolling() {
    // Stop any existing polling
    if (syncPollInterval) {
        clearInterval(syncPollInterval);
    }
    
    // Poll every 2 seconds
    syncPollInterval = setInterval(async () => {
        const inProgress = await loadSyncProgress();
        
        // Also refresh creators list to show updated post counts
        await loadCreators();
        
        if (!inProgress) {
            clearInterval(syncPollInterval);
            syncPollInterval = null;
            showToast('Sync completed!', 'success');
            await loadSyncStatus();
        }
    }, 2000);
}

async function quickSync() {
    try {
        const result = await api('/api/sync/quick', { method: 'POST' });
        if (result.status === 'already_running') {
            showToast('Sync already in progress', 'error');
        } else {
            showToast('Starting quick sync...', 'success');
            startSyncProgressPolling();
        }
    } catch (error) {
        console.error('Failed to start sync:', error);
    }
}

async function fullSync() {
    try {
        const result = await api('/api/sync/full', { method: 'POST' });
        if (result.status === 'already_running') {
            showToast('Sync already in progress', 'error');
        } else {
            showToast('Starting full sync...', 'success');
            startSyncProgressPolling();
        }
    } catch (error) {
        console.error('Failed to start sync:', error);
    }
}

async function toggleBackgroundSync() {
    try {
        if (state.syncRunning) {
            await api('/api/sync/stop-background', { method: 'POST' });
            showToast('Background sync stopped', 'success');
        } else {
            await api('/api/sync/start-background', { method: 'POST' });
            showToast('Background sync started', 'success');
        }
        await loadSyncStatus();
    } catch (error) {
        console.error('Failed to toggle sync:', error);
    }
}

async function updateInterval() {
    const hours = parseFloat(document.getElementById('sync-interval').value);
    
    if (isNaN(hours) || hours <= 0) {
        showToast('Please enter a valid interval', 'error');
        return;
    }
    
    try {
        await api(`/api/settings/interval?hours=${hours}`, { method: 'PUT' });
        showToast(`Interval set to ${hours} hours`, 'success');
    } catch (error) {
        console.error('Failed to update interval:', error);
    }
}

/* ============================================================================
   Utilities
   ============================================================================ */

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    
    // Show toast
    setTimeout(() => toast.classList.remove('hidden'), 10);
    
    // Hide after 3 seconds
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

/* ============================================================================
   Initialization
   ============================================================================ */

document.addEventListener('DOMContentLoaded', async () => {
    // Load runtime configuration first
    await loadConfig();
    
    // Initialize PWA and offline support
    await registerServiceWorker();
    await initOfflineDB();
    
    // Set initial online state
    if (!navigator.onLine) {
        state.isOnline = false;
        document.body.classList.add('offline-mode');
    }
    
    // Check authentication first
    const isAuthenticated = await checkAuth();
    
    if (state.authRequired && !isAuthenticated) {
        showLoginScreen();
    } else {
        hideLoginScreen();
        loadCreators();
    }
    
    // Handle back button on mobile
    window.addEventListener('popstate', () => {
        goBack();
    });
    
    // Infinite scroll for posts
    const postsView = document.getElementById('view-posts');
    postsView.addEventListener('scroll', () => {
        if (postsView.scrollTop + postsView.clientHeight >= postsView.scrollHeight - 100) {
            if (state.posts.length >= state.postsOffset + state.postsLimit) {
                state.postsOffset += state.postsLimit;
                loadPosts(true);
            }
        }
    });
    
    // Enter key in modal
    document.getElementById('new-creator-url').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addCreator();
    });
    
    // Click outside modal to close
    document.getElementById('modal-add-creator').addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) hideModal();
    });
});
