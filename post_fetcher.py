"""Post fetcher service for downloading Patreon posts."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from config import Config
from patreon_auth_selenium import PatreonAuthSelenium
from patreon_api import PatreonAPIClient
from patreon_scraper import PatreonScraper, Post
from post_storage import PostStorage, StoredPost


class PostFetcher:
    """Service for fetching and storing Patreon posts."""
    
    def __init__(self, storage: PostStorage = None, settings_path: str = "./settings.json"):
        self.settings_path = Path(settings_path)
        self.settings = self._load_settings()
        self.storage = storage or PostStorage(self.settings['storage']['database'])
        self.auth = None
        self.api_client = None
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file."""
        if not self.settings_path.exists():
            # Create default settings
            default_settings = {
                "creators": [],
                "sync": {
                    "interval_hours": 2,
                    "auto_start": False
                },
                "storage": {
                    "posts_dir": "./data/posts",
                    "database": "./data/patreon_posts.db"
                }
            }
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_path, 'w') as f:
                json.dump(default_settings, f, indent=4)
            return default_settings
        
        with open(self.settings_path, 'r') as f:
            return json.load(f)
    
    def save_settings(self):
        """Save current settings to file."""
        with open(self.settings_path, 'w') as f:
            json.dump(self.settings, f, indent=4)
    
    def add_creator(self, url: str, name: Optional[str] = None) -> str:
        """
        Add a creator to follow.
        
        Args:
            url: Patreon creator URL (e.g., https://www.patreon.com/c/millennialmage/posts)
            name: Optional display name
            
        Returns:
            Creator slug
        """
        # Extract creator slug from URL
        slug = self._extract_slug(url)
        
        if not name:
            name = slug.replace('-', ' ').title()
        
        # Check if already exists
        for creator in self.settings['creators']:
            if creator['url'] == url or self._extract_slug(creator['url']) == slug:
                print(f"Creator '{name}' is already in your list.")
                return slug
        
        # Add to settings
        self.settings['creators'].append({
            "name": name,
            "url": url,
            "enabled": True
        })
        self.save_settings()
        
        # Add to database
        self.storage.save_creator(slug, name, url, enabled=True)
        
        print(f"✓ Added creator: {name} ({slug})")
        return slug
    
    def remove_creator(self, slug_or_url: str) -> bool:
        """Remove a creator from the follow list."""
        slug = self._extract_slug(slug_or_url) if '/' in slug_or_url else slug_or_url
        
        for i, creator in enumerate(self.settings['creators']):
            if self._extract_slug(creator['url']) == slug:
                removed = self.settings['creators'].pop(i)
                self.save_settings()
                print(f"✓ Removed creator: {removed['name']}")
                return True
        
        print(f"Creator '{slug}' not found.")
        return False
    
    def list_creators(self) -> List[Dict[str, Any]]:
        """List all followed creators with their status."""
        creators = []
        for creator in self.settings['creators']:
            slug = self._extract_slug(creator['url'])
            post_count = self.storage.get_post_count(slug)
            latest = self.storage.get_latest_post_date(slug)
            
            creators.append({
                'name': creator['name'],
                'slug': slug,
                'url': creator['url'],
                'enabled': creator.get('enabled', True),
                'post_count': post_count,
                'latest_post': latest
            })
        return creators
    
    def _extract_slug(self, url: str) -> str:
        """Extract creator slug from Patreon URL."""
        # Handle various URL formats:
        # https://www.patreon.com/c/millennialmage/posts
        # https://www.patreon.com/millennialmage
        # https://www.patreon.com/c/millennialmage
        
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Remove 'c/' prefix if present
        if path.startswith('c/'):
            path = path[2:]
        
        # Remove '/posts' suffix if present
        if path.endswith('/posts'):
            path = path[:-6]
        
        # Return the creator slug
        return path.split('/')[0]
    
    def _extract_post_id(self, url: str) -> str:
        """Extract unique post ID from post URL."""
        # URL format: https://www.patreon.com/posts/chapter-xxx-123456
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        if path.startswith('posts/'):
            return path[6:]  # Everything after 'posts/'
        
        return path
    
    def authenticate(self, headless: bool = True) -> bool:
        """Authenticate with Patreon."""
        Config.validate()
        
        print("Authenticating with Patreon...")
        self.auth = PatreonAuthSelenium(headless=headless)
        
        if not self.auth.login():
            print("✗ Authentication failed. Please check your credentials in .env")
            return False
        
        self.api_client = PatreonAPIClient(self.auth)
        return True
    
    def fetch_all_posts(self, creator_url: str, force_refresh: bool = False) -> int:
        """
        Fetch ALL posts from a creator (initial full pull).
        
        Args:
            creator_url: Patreon creator URL
            force_refresh: If True, re-fetch all posts even if already stored
            
        Returns:
            Number of new posts added
        """
        if not self.auth or not self.api_client:
            if not self.authenticate():
                return 0
        
        slug = self._extract_slug(creator_url)
        existing_ids = set() if force_refresh else self.storage.get_all_post_ids(slug)
        
        print(f"\nFetching all posts from {creator_url}...")
        print(f"  Existing posts in database: {len(existing_ids)}")
        
        # Get campaign ID
        campaign_id, user_id = self.api_client.get_campaign_id_from_url(
            creator_url, auth_driver=self.auth
        )
        
        posts = []
        if campaign_id:
            print(f"  Using Patreon API (Campaign: {campaign_id})")
            posts = self.api_client.get_campaign_posts(campaign_id, user_id=user_id)
        
        # Fallback to scraping if API fails
        if not posts:
            print("  Falling back to HTML scraping...")
            scraper = PatreonScraper(self.auth)
            posts = scraper.get_creator_posts(creator_url)
        
        if not posts:
            print("✗ No posts found.")
            self.storage.log_sync(slug, 0, "error", "No posts found")
            return 0
        
        print(f"  Found {len(posts)} total posts")
        
        # Convert and store posts
        new_count = 0
        for post in posts:
            post_id = self._extract_post_id(post.url)
            
            if post_id in existing_ids and not force_refresh:
                continue
            
            stored_post = StoredPost(
                id=post_id,
                creator_slug=slug,
                title=post.title,
                content=post.content,
                url=post.url,
                published_date=post.published_date,
                images=post.images,
                fetched_at=datetime.utcnow().isoformat()
            )
            
            if self.storage.save_post(stored_post):
                new_count += 1
        
        # Update creator sync info
        self.storage.update_creator_sync(slug, new_count)
        self.storage.log_sync(slug, new_count, "success")
        
        print(f"✓ Added {new_count} new posts (total: {self.storage.get_post_count(slug)})")
        return new_count
    
    def fetch_recent_posts(self, creator_url: str, check_count: int = 20) -> int:
        """
        Fetch only recent posts (for periodic sync).
        
        Args:
            creator_url: Patreon creator URL
            check_count: Number of recent posts to check
            
        Returns:
            Number of new posts added
        """
        if not self.auth or not self.api_client:
            if not self.authenticate():
                return 0
        
        slug = self._extract_slug(creator_url)
        existing_ids = self.storage.get_all_post_ids(slug)
        
        print(f"\nChecking for new posts from {slug}...")
        
        # Get campaign ID
        campaign_id, user_id = self.api_client.get_campaign_id_from_url(
            creator_url, auth_driver=self.auth
        )
        
        posts = []
        if campaign_id:
            posts = self.api_client.get_campaign_posts(
                campaign_id, user_id=user_id, limit=check_count
            )
        
        if not posts:
            print("  Falling back to HTML scraping...")
            scraper = PatreonScraper(self.auth)
            posts = scraper.get_creator_posts(creator_url, limit=check_count)
        
        # Find new posts
        new_count = 0
        for post in posts:
            post_id = self._extract_post_id(post.url)
            
            if post_id in existing_ids:
                continue
            
            stored_post = StoredPost(
                id=post_id,
                creator_slug=slug,
                title=post.title,
                content=post.content,
                url=post.url,
                published_date=post.published_date,
                images=post.images,
                fetched_at=datetime.utcnow().isoformat()
            )
            
            if self.storage.save_post(stored_post):
                new_count += 1
                print(f"  + New post: {post.title}")
        
        # Update sync info
        self.storage.update_creator_sync(slug, new_count)
        self.storage.log_sync(slug, new_count, "success")
        
        if new_count == 0:
            print("  No new posts found.")
        else:
            print(f"✓ Added {new_count} new posts")
        
        return new_count
    
    def sync_all_creators(self, full_sync: bool = False) -> Dict[str, int]:
        """
        Sync all enabled creators.
        
        Args:
            full_sync: If True, do a full fetch; otherwise just check recent posts
            
        Returns:
            Dict mapping creator slug to new post count
        """
        results = {}
        
        for creator in self.settings['creators']:
            if not creator.get('enabled', True):
                continue
            
            slug = self._extract_slug(creator['url'])
            
            try:
                if full_sync:
                    results[slug] = self.fetch_all_posts(creator['url'])
                else:
                    results[slug] = self.fetch_recent_posts(creator['url'])
            except Exception as e:
                print(f"✗ Error syncing {creator['name']}: {e}")
                self.storage.log_sync(slug, 0, "error", str(e))
                results[slug] = 0
        
        return results
    
    def close(self):
        """Clean up resources."""
        if self.auth:
            self.auth.close()
            self.auth = None
            self.api_client = None


def extract_post_slug_from_url(url: str) -> str:
    """Utility function to extract post slug from URL."""
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    if path.startswith('posts/'):
        return path[6:]
    return path
