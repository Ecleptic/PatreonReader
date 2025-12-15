"""
FastAPI server for Patreon Post Reader.

This server handles:
- Serving posts from the database
- Managing creators
- Triggering syncs
- Serving the web frontend

Credentials are kept server-side only - never exposed to the frontend.
"""

import os
import sys
import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from post_storage import PostStorage, StoredPost
from post_fetcher import PostFetcher
from sync_service import SyncService


# ============================================================================
# Logging Configuration
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # "text" or "json"

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)

logger = logging.getLogger("patreon_reader")


# ============================================================================
# Configuration
# ============================================================================

SETTINGS_PATH = "./settings.json"
STATIC_DIR = Path("./static")

# App URL - public-facing URL for the application
# Used by PWA and frontend to connect to the correct backend
# If not set, defaults to same-origin (empty string)
APP_URL = os.getenv("APP_URL", "").rstrip("/")

# Authentication configuration
# Set API_TOKEN in .env to require authentication
# If not set, auth is disabled (for local development)
API_TOKEN = os.getenv("API_TOKEN")
AUTH_ENABLED = API_TOKEN is not None and len(API_TOKEN) > 0

# Token hashing for secure comparison
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

API_TOKEN_HASH = hash_token(API_TOKEN) if AUTH_ENABLED else None

# Security scheme
security = HTTPBearer(auto_error=False)

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Verify the API token if authentication is enabled."""
    if not AUTH_ENABLED:
        return True
    
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide Bearer token.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Secure comparison to prevent timing attacks
    if not secrets.compare_digest(hash_token(credentials.credentials), API_TOKEN_HASH):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return True


# ============================================================================
# Pydantic Models (API schemas)
# ============================================================================

class CreatorCreate(BaseModel):
    url: str
    name: Optional[str] = None

class CreatorResponse(BaseModel):
    name: str
    slug: str
    url: str
    enabled: bool
    post_count: int
    latest_post: Optional[str]
    unread_count: Optional[int] = None

class PostSummary(BaseModel):
    id: str
    title: str
    published_date: Optional[str]
    creator_slug: str
    is_read: bool = False

class PostDetail(BaseModel):
    id: str
    creator_slug: str
    title: str
    content: str
    url: str
    published_date: Optional[str]
    images: List[str]
    fetched_at: str
    is_read: bool = False
    prev_post_id: Optional[str] = None
    next_post_id: Optional[str] = None

class SyncStatus(BaseModel):
    running: bool
    interval_hours: float
    total_creators: int
    total_posts: int

class SyncResult(BaseModel):
    creator: str
    new_posts: int
    status: str


# ============================================================================
# App initialization
# ============================================================================

# Global instances
storage: Optional[PostStorage] = None
fetcher: Optional[PostFetcher] = None
sync_service: Optional[SyncService] = None

# Sync state tracking
sync_state = {
    "in_progress": False,
    "current_creator": None,
    "message": "",
    "posts_added": 0
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global storage, fetcher, sync_service
    
    # Startup
    logger.info("Starting Patreon Reader API Server...")
    storage = PostStorage()
    fetcher = PostFetcher(storage=storage, settings_path=SETTINGS_PATH)
    sync_service = SyncService(settings_path=SETTINGS_PATH)
    
    # Create static directory if needed
    STATIC_DIR.mkdir(exist_ok=True)
    
    logger.info("=" * 50)
    logger.info("Patreon Reader API Server")
    logger.info("=" * 50)
    logger.info(f"API docs: http://localhost:8000/docs")
    logger.info(f"Web app:  http://localhost:8000/")
    logger.info(f"Auth:     {'ENABLED (API_TOKEN set)' if AUTH_ENABLED else 'DISABLED (set API_TOKEN in .env)'}")
    logger.info("=" * 50)
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if sync_service:
        sync_service.close()
    if fetcher:
        fetcher.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Patreon Reader API",
    description="API for managing and reading Patreon posts",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for mobile app / web frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# API Routes - Auth & Health
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {
        "status": "healthy",
        "auth_enabled": AUTH_ENABLED,
        "version": "1.0.0"
    }


@app.get("/api/config")
async def get_config():
    """Get runtime configuration for the frontend (no auth required).
    
    Returns configuration that the frontend needs to connect properly.
    Does NOT expose sensitive data like tokens or credentials.
    """
    return {
        "api_url": APP_URL,  # Backend API URL (empty = same origin)
        "auth_enabled": AUTH_ENABLED,
        "version": "1.0.0"
    }


@app.get("/api/auth/check", dependencies=[Depends(verify_token)])
async def check_auth():
    """Check if authentication is valid."""
    return {"authenticated": True}


# ============================================================================
# API Routes - Creators
# ============================================================================

@app.get("/api/creators", response_model=List[CreatorResponse], dependencies=[Depends(verify_token)])
async def list_creators():
    """List all followed creators."""
    creators = fetcher.list_creators()
    # Add unread counts
    for c in creators:
        c['unread_count'] = storage.get_unread_count(c['slug'])
    return [CreatorResponse(**c) for c in creators]


@app.post("/api/creators", response_model=CreatorResponse, dependencies=[Depends(verify_token)])
async def add_creator(creator: CreatorCreate, background_tasks: BackgroundTasks):
    """Add a new creator to follow and start syncing."""
    slug = fetcher.add_creator(creator.url, creator.name)
    
    # Get the full creator info
    creators = fetcher.list_creators()
    creator_info = None
    for c in creators:
        if c['slug'] == slug:
            creator_info = c
            break
    
    if not creator_info:
        raise HTTPException(status_code=500, detail="Failed to add creator")
    
    # Auto-start full sync for this creator
    def sync_new_creator():
        global sync_state
        sync_state["in_progress"] = True
        sync_state["current_creator"] = creator_info['name']
        sync_state["message"] = f"Syncing {creator_info['name']}..."
        sync_state["posts_added"] = 0
        logger.info(f"Starting sync for new creator: {creator_info['name']}")
        try:
            if not fetcher.auth:
                fetcher.authenticate(headless=True)
            count = fetcher.fetch_all_posts(creator.url)
            sync_state["posts_added"] = count
            sync_state["message"] = f"Completed: {count} posts from {creator_info['name']}"
            logger.info(f"Sync complete for {creator_info['name']}: {count} posts")
        except Exception as e:
            sync_state["message"] = f"Error syncing {creator_info['name']}: {str(e)}"
            logger.error(f"Sync error for {creator_info['name']}: {e}", exc_info=True)
        finally:
            sync_state["in_progress"] = False
            sync_state["current_creator"] = None
    
    background_tasks.add_task(sync_new_creator)
    
    return CreatorResponse(**creator_info)


@app.delete("/api/creators/{slug}", dependencies=[Depends(verify_token)])
async def remove_creator(slug: str):
    """Remove a creator from the follow list."""
    logger.info(f"Removing creator: {slug}")
    if fetcher.remove_creator(slug):
        return {"status": "removed", "slug": slug}
    raise HTTPException(status_code=404, detail="Creator not found")


# ============================================================================
# API Routes - Posts
# ============================================================================

@app.get("/api/posts/{creator_slug}", response_model=List[PostSummary], dependencies=[Depends(verify_token)])
async def list_posts(
    creator_slug: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None
):
    """List posts from a creator."""
    if search:
        posts = storage.search_posts(search, creator_slug)
        # Apply limit/offset to search results
        posts = posts[offset:offset + limit]
    else:
        posts = storage.get_posts_by_creator(creator_slug, limit=limit, offset=offset)
    
    return [
        PostSummary(
            id=p.id,
            title=p.title,
            published_date=p.published_date,
            creator_slug=p.creator_slug,
            is_read=p.is_read
        )
        for p in posts
    ]


@app.get("/api/posts/{creator_slug}/{post_id}", response_model=PostDetail, dependencies=[Depends(verify_token)])
async def get_post(creator_slug: str, post_id: str, mark_read: bool = True):
    """Get a specific post with full content. Auto-marks as read by default."""
    post = storage.get_post(post_id, creator_slug)
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Auto-mark as read when viewed
    if mark_read and not post.is_read:
        storage.mark_post_read(post_id, creator_slug, True)
        post.is_read = True
    
    # Get adjacent posts for navigation
    adjacent = storage.get_adjacent_posts(post_id, creator_slug)
    
    return PostDetail(
        id=post.id,
        creator_slug=post.creator_slug,
        title=post.title,
        content=post.content,
        url=post.url,
        published_date=post.published_date,
        images=post.images,
        fetched_at=post.fetched_at,
        is_read=post.is_read,
        prev_post_id=adjacent["prev"],
        next_post_id=adjacent["next"]
    )


@app.get("/api/posts/{creator_slug}/count", dependencies=[Depends(verify_token)])
async def get_post_count(creator_slug: str):
    """Get total post count for a creator."""
    count = storage.get_post_count(creator_slug)
    return {"creator": creator_slug, "count": count}


@app.put("/api/posts/{creator_slug}/{post_id}/read", dependencies=[Depends(verify_token)])
async def mark_post_read(creator_slug: str, post_id: str, is_read: bool = True):
    """Mark a post as read or unread."""
    success = storage.mark_post_read(post_id, creator_slug, is_read)
    if not success:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"status": "ok", "is_read": is_read}


@app.get("/api/search", dependencies=[Depends(verify_token)])
async def search_all_posts(
    q: str = Query(..., min_length=1),
    creator: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """Search posts across all creators or a specific creator."""
    posts = storage.search_posts(q, creator)[:limit]
    
    return [
        PostSummary(
            id=p.id,
            title=p.title,
            published_date=p.published_date,
            creator_slug=p.creator_slug,
            is_read=p.is_read
        )
        for p in posts
    ]


# ============================================================================
# API Routes - Sync
# ============================================================================

@app.get("/api/sync/status", response_model=SyncStatus, dependencies=[Depends(verify_token)])
async def get_sync_status():
    """Get current sync service status."""
    status = sync_service.get_status()
    return SyncStatus(
        running=status['running'],
        interval_hours=status['interval_hours'],
        total_creators=len(status['creators']),
        total_posts=status['total_posts']
    )


@app.get("/api/sync/progress", dependencies=[Depends(verify_token)])
async def get_sync_progress():
    """Get current sync progress."""
    return {
        "in_progress": sync_state["in_progress"],
        "current_creator": sync_state["current_creator"],
        "message": sync_state["message"],
        "posts_added": sync_state["posts_added"]
    }


@app.post("/api/sync/quick", dependencies=[Depends(verify_token)])
async def trigger_quick_sync(background_tasks: BackgroundTasks):
    """Trigger a quick sync (check recent posts only)."""
    global sync_state
    
    if sync_state["in_progress"]:
        logger.info("Quick sync requested but already running")
        return {"status": "already_running", "message": sync_state["message"]}
    
    def do_sync():
        global sync_state
        sync_state["in_progress"] = True
        sync_state["message"] = "Quick sync in progress..."
        logger.info("Starting quick sync")
        try:
            sync_service.quick_sync()
            sync_state["message"] = "Quick sync completed"
            logger.info("Quick sync completed successfully")
        except Exception as e:
            sync_state["message"] = f"Sync error: {str(e)}"
            logger.error(f"Quick sync error: {e}", exc_info=True)
        finally:
            sync_state["in_progress"] = False
            sync_state["current_creator"] = None
    
    background_tasks.add_task(do_sync)
    return {"status": "started", "type": "quick"}


@app.post("/api/sync/full", dependencies=[Depends(verify_token)])
async def trigger_full_sync(background_tasks: BackgroundTasks):
    """Trigger a full sync (download all posts)."""
    global sync_state
    
    if sync_state["in_progress"]:
        logger.info("Full sync requested but already running")
        return {"status": "already_running", "message": sync_state["message"]}
    
    def do_sync():
        global sync_state
        sync_state["in_progress"] = True
        sync_state["message"] = "Full sync in progress..."
        logger.info("Starting full sync")
        try:
            sync_service.initial_sync()
            sync_state["message"] = "Full sync completed"
            logger.info("Full sync completed successfully")
        except Exception as e:
            sync_state["message"] = f"Sync error: {str(e)}"
            logger.error(f"Full sync error: {e}", exc_info=True)
        finally:
            sync_state["in_progress"] = False
            sync_state["current_creator"] = None
    
    background_tasks.add_task(do_sync)
    return {"status": "started", "type": "full"}


@app.post("/api/sync/start-background", dependencies=[Depends(verify_token)])
async def start_background_sync():
    """Start the background sync service."""
    sync_service.start_background_sync()
    return {"status": "started", "interval_hours": sync_service.interval_hours}


@app.post("/api/sync/stop-background", dependencies=[Depends(verify_token)])
async def stop_background_sync():
    """Stop the background sync service."""
    sync_service.stop_background_sync()
    return {"status": "stopped"}


@app.get("/api/sync/history/{creator_slug}", dependencies=[Depends(verify_token)])
async def get_sync_history(creator_slug: str, limit: int = 10):
    """Get sync history for a creator."""
    history = storage.get_sync_history(creator_slug, limit)
    return history


# ============================================================================
# API Routes - Settings
# ============================================================================

@app.get("/api/settings/interval", dependencies=[Depends(verify_token)])
async def get_sync_interval():
    """Get current sync interval."""
    return {"interval_hours": sync_service.interval_hours}


@app.put("/api/settings/interval", dependencies=[Depends(verify_token)])
async def set_sync_interval(hours: float = Query(..., gt=0)):
    """Set sync interval in hours."""
    sync_service.set_interval(hours)
    return {"interval_hours": hours}


# ============================================================================
# E-Paper Reader Routes (simplified HTML for e-ink devices)
# ============================================================================

@app.get("/reader/", response_class=HTMLResponse)
async def serve_reader_index():
    """Serve the e-paper optimized post list."""
    reader_path = STATIC_DIR / "reader-index.html"
    if reader_path.exists():
        return FileResponse(reader_path)
    raise HTTPException(status_code=404, detail="E-paper reader not found")


@app.get("/reader/post", response_class=HTMLResponse)
async def serve_reader_post():
    """Serve the e-paper optimized post view."""
    reader_path = STATIC_DIR / "reader.html"
    if reader_path.exists():
        return FileResponse(reader_path)
    raise HTTPException(status_code=404, detail="E-paper reader not found")


# ============================================================================
# Web Frontend Routes
# ============================================================================

@app.get("/sw.js")
async def serve_service_worker():
    """Serve service worker from root for proper scope."""
    sw_path = STATIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Service worker not found")


@app.get("/manifest.json")
async def serve_manifest():
    """Serve PWA manifest from root."""
    manifest_path = STATIC_DIR / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main web app."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    
    # Fallback simple HTML if static files not built yet
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Patreon Reader</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: system-ui; max-width: 600px; margin: 50px auto; padding: 20px; }
            h1 { color: #f96854; }
            a { color: #f96854; }
        </style>
    </head>
    <body>
        <h1>Patreon Reader</h1>
        <p>API is running! Web frontend not yet built.</p>
        <p>API Documentation: <a href="/docs">/docs</a></p>
        <p>Use the CLI for now: <code>python3 post_manager.py --help</code></p>
    </body>
    </html>
    """


# Mount static files (for JS, CSS, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# Run server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
