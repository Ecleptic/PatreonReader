"""Post storage using SQLite for managing Patreon posts."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class StoredPost:
    """Represents a stored Patreon post."""
    id: str  # Unique post ID from URL slug
    creator_slug: str  # Creator identifier (e.g., "example-creator")
    title: str
    content: str  # HTML content
    url: str
    published_date: str
    images: List[str]
    fetched_at: str
    raw_data: Optional[str] = None  # JSON string of original API response
    is_read: bool = False  # Whether the post has been read
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoredPost':
        return cls(**data)


class PostStorage:
    """SQLite-based storage for Patreon posts."""
    
    def __init__(self, db_path: str = "./data/patreon_posts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize the SQLite database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Posts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id TEXT PRIMARY KEY,
                    creator_slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    url TEXT,
                    published_date TEXT,
                    images TEXT,
                    fetched_at TEXT,
                    raw_data TEXT,
                    UNIQUE(creator_slug, id)
                )
            ''')
            
            # Creators table for tracking sync state
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS creators (
                    slug TEXT PRIMARY KEY,
                    name TEXT,
                    url TEXT,
                    last_sync TEXT,
                    total_posts INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1
                )
            ''')
            
            # Sync log for tracking updates
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_slug TEXT,
                    sync_time TEXT,
                    posts_added INTEGER,
                    status TEXT,
                    error_message TEXT
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_creator ON posts(creator_slug)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_date DESC)')
            
            # Add is_read column if it doesn't exist (migration)
            cursor.execute("PRAGMA table_info(posts)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'is_read' not in columns:
                cursor.execute('ALTER TABLE posts ADD COLUMN is_read INTEGER DEFAULT 0')
            
            conn.commit()
    
    def save_post(self, post: StoredPost) -> bool:
        """
        Save a post to the database.
        
        Returns True if new post was inserted, False if updated.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Check if post exists
            cursor.execute('SELECT id FROM posts WHERE id = ? AND creator_slug = ?', 
                          (post.id, post.creator_slug))
            exists = cursor.fetchone() is not None
            
            cursor.execute('''
                INSERT OR REPLACE INTO posts 
                (id, creator_slug, title, content, url, published_date, images, fetched_at, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                post.id,
                post.creator_slug,
                post.title,
                post.content,
                post.url,
                post.published_date,
                json.dumps(post.images),
                post.fetched_at,
                post.raw_data
            ))
            conn.commit()
            
            return not exists
    
    def save_posts(self, posts: List[StoredPost]) -> int:
        """
        Save multiple posts. Returns count of new posts added.
        """
        new_count = 0
        for post in posts:
            if self.save_post(post):
                new_count += 1
        return new_count
    
    def get_post(self, post_id: str, creator_slug: str) -> Optional[StoredPost]:
        """Get a specific post by ID and creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, creator_slug, title, content, url, published_date, 
                       images, fetched_at, raw_data, COALESCE(is_read, 0)
                FROM posts 
                WHERE id = ? AND creator_slug = ?
            ''', (post_id, creator_slug))
            
            row = cursor.fetchone()
            if row:
                return StoredPost(
                    id=row[0],
                    creator_slug=row[1],
                    title=row[2],
                    content=row[3],
                    url=row[4],
                    published_date=row[5],
                    images=json.loads(row[6]) if row[6] else [],
                    fetched_at=row[7],
                    raw_data=row[8],
                    is_read=bool(row[9])
                )
            return None
    
    def get_posts_by_creator(self, creator_slug: str, 
                             limit: Optional[int] = None,
                             offset: int = 0,
                             order_desc: bool = True) -> List[StoredPost]:
        """Get all posts for a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            order = "DESC" if order_desc else "ASC"
            query = f'''
                SELECT id, creator_slug, title, content, url, published_date, 
                       images, fetched_at, raw_data, COALESCE(is_read, 0)
                FROM posts 
                WHERE creator_slug = ?
                ORDER BY published_date {order}
            '''
            
            if limit:
                query += f' LIMIT {limit} OFFSET {offset}'
            
            cursor.execute(query, (creator_slug,))
            
            posts = []
            for row in cursor.fetchall():
                posts.append(StoredPost(
                    id=row[0],
                    creator_slug=row[1],
                    title=row[2],
                    content=row[3],
                    url=row[4],
                    published_date=row[5],
                    images=json.loads(row[6]) if row[6] else [],
                    fetched_at=row[7],
                    raw_data=row[8],
                    is_read=bool(row[9])
                ))
            return posts
    
    def get_latest_post_date(self, creator_slug: str) -> Optional[str]:
        """Get the published date of the most recent post for a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT published_date 
                FROM posts 
                WHERE creator_slug = ?
                ORDER BY published_date DESC 
                LIMIT 1
            ''', (creator_slug,))
            
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_post_count(self, creator_slug: str) -> int:
        """Get total post count for a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM posts WHERE creator_slug = ?', 
                          (creator_slug,))
            return cursor.fetchone()[0]
    
    def search_posts(self, query: str, creator_slug: Optional[str] = None) -> List[StoredPost]:
        """Search posts by title or content."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            search_term = f'%{query}%'
            
            if creator_slug:
                cursor.execute('''
                    SELECT id, creator_slug, title, content, url, published_date, 
                           images, fetched_at, raw_data, COALESCE(is_read, 0)
                    FROM posts 
                    WHERE creator_slug = ? AND (title LIKE ? OR content LIKE ?)
                    ORDER BY published_date DESC
                ''', (creator_slug, search_term, search_term))
            else:
                cursor.execute('''
                    SELECT id, creator_slug, title, content, url, published_date, 
                           images, fetched_at, raw_data, COALESCE(is_read, 0)
                    FROM posts 
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY published_date DESC
                ''', (search_term, search_term))
            
            posts = []
            for row in cursor.fetchall():
                posts.append(StoredPost(
                    id=row[0],
                    creator_slug=row[1],
                    title=row[2],
                    content=row[3],
                    url=row[4],
                    published_date=row[5],
                    images=json.loads(row[6]) if row[6] else [],
                    fetched_at=row[7],
                    raw_data=row[8],
                    is_read=bool(row[9])
                ))
            return posts
    
    def mark_post_read(self, post_id: str, creator_slug: str, is_read: bool = True):
        """Mark a post as read or unread."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE posts SET is_read = ? WHERE id = ? AND creator_slug = ?
            ''', (1 if is_read else 0, post_id, creator_slug))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_unread_count(self, creator_slug: str) -> int:
        """Get count of unread posts for a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM posts 
                WHERE creator_slug = ? AND (is_read IS NULL OR is_read = 0)
            ''', (creator_slug,))
            return cursor.fetchone()[0]
    
    def get_adjacent_posts(self, post_id: str, creator_slug: str) -> Dict[str, Optional[str]]:
        """Get the previous and next post IDs for navigation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get current post's published_date and fetched_at
            cursor.execute('''
                SELECT published_date, fetched_at FROM posts 
                WHERE id = ? AND creator_slug = ?
            ''', (post_id, creator_slug))
            row = cursor.fetchone()
            if not row:
                return {"prev": None, "next": None}
            
            current_date = row[0]
            current_fetched = row[1]
            
            # Use published_date if available, otherwise use fetched_at
            if current_date:
                # Get previous post (older - earlier date)
                cursor.execute('''
                    SELECT id FROM posts 
                    WHERE creator_slug = ? AND published_date < ?
                    ORDER BY published_date DESC
                    LIMIT 1
                ''', (creator_slug, current_date))
                prev_row = cursor.fetchone()
                
                # Get next post (newer - later date)
                cursor.execute('''
                    SELECT id FROM posts 
                    WHERE creator_slug = ? AND published_date > ?
                    ORDER BY published_date ASC
                    LIMIT 1
                ''', (creator_slug, current_date))
                next_row = cursor.fetchone()
            else:
                # Fallback: use row order based on fetched_at
                cursor.execute('''
                    SELECT id FROM posts 
                    WHERE creator_slug = ? AND fetched_at < ?
                    ORDER BY fetched_at DESC
                    LIMIT 1
                ''', (creator_slug, current_fetched))
                prev_row = cursor.fetchone()
                
                cursor.execute('''
                    SELECT id FROM posts 
                    WHERE creator_slug = ? AND fetched_at > ?
                    ORDER BY fetched_at ASC
                    LIMIT 1
                ''', (creator_slug, current_fetched))
                next_row = cursor.fetchone()
            
            return {
                "prev": prev_row[0] if prev_row else None,
                "next": next_row[0] if next_row else None
            }
    
    def get_all_post_ids(self, creator_slug: str) -> set:
        """Get all post IDs for a creator (for quick duplicate checking)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM posts WHERE creator_slug = ?', (creator_slug,))
            return {row[0] for row in cursor.fetchall()}
    
    # Creator management
    def save_creator(self, slug: str, name: str, url: str, enabled: bool = True):
        """Save or update a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO creators (slug, name, url, enabled)
                VALUES (?, ?, ?, ?)
            ''', (slug, name, url, 1 if enabled else 0))
            conn.commit()
    
    def get_creators(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """Get all creators."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if enabled_only:
                cursor.execute('''
                    SELECT slug, name, url, last_sync, total_posts, enabled
                    FROM creators WHERE enabled = 1
                ''')
            else:
                cursor.execute('''
                    SELECT slug, name, url, last_sync, total_posts, enabled
                    FROM creators
                ''')
            
            creators = []
            for row in cursor.fetchall():
                creators.append({
                    'slug': row[0],
                    'name': row[1],
                    'url': row[2],
                    'last_sync': row[3],
                    'total_posts': row[4],
                    'enabled': bool(row[5])
                })
            return creators
    
    def update_creator_sync(self, slug: str, posts_added: int = 0):
        """Update creator's last sync time and post count."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get current post count
            post_count = self.get_post_count(slug)
            
            cursor.execute('''
                UPDATE creators 
                SET last_sync = ?, total_posts = ?
                WHERE slug = ?
            ''', (datetime.utcnow().isoformat(), post_count, slug))
            conn.commit()
    
    def log_sync(self, creator_slug: str, posts_added: int, 
                 status: str = "success", error_message: str = None):
        """Log a sync operation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_log (creator_slug, sync_time, posts_added, status, error_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (creator_slug, datetime.utcnow().isoformat(), posts_added, status, error_message))
            conn.commit()
    
    def get_sync_history(self, creator_slug: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sync history for a creator."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sync_time, posts_added, status, error_message
                FROM sync_log
                WHERE creator_slug = ?
                ORDER BY sync_time DESC
                LIMIT ?
            ''', (creator_slug, limit))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'sync_time': row[0],
                    'posts_added': row[1],
                    'status': row[2],
                    'error_message': row[3]
                })
            return history
