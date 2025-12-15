"""Patreon content scraper."""

import re
import json
import time
import threading
from typing import List, Dict, Optional, Union
from bs4 import BeautifulSoup
from pathlib import Path
from config import Config
import requests


# ============================================================================
# Rate Limiter
# ============================================================================

class RateLimiter:
    """
    Simple rate limiter to prevent hitting Patreon's servers too hard.
    
    Default: 1 request per 2 seconds (30 requests/minute)
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, min_interval: float = 2.0):
        if self._initialized:
            return
        self.min_interval = min_interval
        self.last_request_time = 0
        self._request_lock = threading.Lock()
        self._initialized = True
    
    def wait(self):
        """Wait until it's safe to make another request."""
        with self._request_lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)
            self.last_request_time = time.time()
    
    def set_interval(self, seconds: float):
        """Update the minimum interval between requests."""
        self.min_interval = max(0.5, seconds)  # At least 0.5 seconds


# Global rate limiter instance
rate_limiter = RateLimiter()


class Post:
    """Represents a Patreon post."""
    
    def __init__(self, title: str, content: str, url: str, 
                 published_date: Optional[str] = None, images: Optional[List[str]] = None):
        self.title = title
        self.content = content
        self.url = url
        self.published_date = published_date
        self.images = images or []
    
    def __repr__(self):
        return f"Post(title='{self.title}', url='{self.url}')"


class PatreonScraper:
    """Scrape posts from Patreon creators."""
    
    def __init__(self, auth_driver):
        """
        Initialize scraper with authenticated Selenium driver.
        
        Args:
            auth_driver: PatreonAuthSelenium instance
        """
        self.auth_driver = auth_driver
        self.session = requests.Session()
        # Copy cookies from Selenium to requests session
        if hasattr(auth_driver, 'driver') and auth_driver.driver:
            for cookie in auth_driver.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])
    
    def get_creator_posts(self, creator_url: str, limit: Optional[int] = None, max_load_more: int = 50) -> List[Post]:
        """
        Fetch all posts from a creator's page.
        
        Args:
            creator_url: URL to the creator's posts page
            limit: Optional limit on number of posts to fetch
            max_load_more: Maximum number of times to click "Load more"
            
        Returns:
            List of Post objects
        """
        posts = []
        
        try:
            print(f"Fetching posts from {creator_url}...")
            print(f"  (This may take a while as we load all posts...)")
            
            # Get page source using Selenium with Load More clicking
            page_source = self.auth_driver.get_page_source(creator_url)
            
            # Parse the page
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Try to find JSON data in scripts
            posts_data = self._extract_posts_from_page(soup)
            
            if posts_data:
                posts = posts_data[:limit] if limit else posts_data
                print(f"✓ Found {len(posts)} posts")
            else:
                print("⚠ Could not extract posts from page")
            
            return posts
            
        except Exception as e:
            print(f"✗ Error fetching posts: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_posts_from_page(self, soup: BeautifulSoup) -> List[Post]:
        """Extract post data from parsed HTML."""
        posts = []
        
        # Look for React data in script tags  
        scripts = soup.find_all('script')
        
        for script in scripts:
            if not script.string:
                continue
            
            text = script.string
            
            # Try to find bootstrap data or other JSON structures
            if 'window.patreon' in text or '__NEXT_DATA__' in text or 'bootstrap' in text:
                try:
                    # Try __NEXT_DATA__ first (modern Next.js pattern)
                    if '__NEXT_DATA__' in text:
                        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', str(soup), re.DOTALL)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                posts_from_json = self._parse_nextjs_data(data)
                                if posts_from_json:
                                    posts.extend(posts_from_json)
                                    continue
                            except:
                                pass
                    
                    # Extract JSON from the script
                    # Common patterns: window.patreon.bootstrap = {...}
                    matches = re.findall(r'window\.patreon\.bootstrap\s*=\s*({.+?});', text, re.DOTALL)
                    if not matches:
                        matches = re.findall(r'bootstrap["\']?\s*:\s*({.+?}),?\s*["\']?', text, re.DOTALL)
                    
                    for match in matches:
                        try:
                            data = json.loads(match)
                            posts_from_json = self._parse_bootstrap_data(data)
                            posts.extend(posts_from_json)
                        except json.JSONDecodeError:
                            continue
                            
                except Exception as e:
                    continue
        
        # Try to find __NEXT_DATA__ script tag directly
        if not posts:
            next_data_script = soup.find('script', id='__NEXT_DATA__', type='application/json')
            if next_data_script and next_data_script.string:
                try:
                    data = json.loads(next_data_script.string)
                    posts = self._parse_nextjs_data(data)
                except:
                    pass
        
        # Fallback: Look for post cards/articles in HTML
        if not posts:
            posts = self._extract_posts_from_html(soup)
        
        return posts
    
    def _parse_nextjs_data(self, data: dict) -> List[Post]:
        """Parse posts from Next.js __NEXT_DATA__ structure."""
        posts = []
        
        try:
            # Navigate Next.js structure
            # Typically: props -> pageProps -> bootstrap -> campaign/post data
            page_props = data.get('props', {}).get('pageProps', {})
            bootstrap = page_props.get('bootstrap', {})
            
            # Try to find posts in various locations
            if bootstrap:
                posts_from_bootstrap = self._parse_bootstrap_data(bootstrap)
                if posts_from_bootstrap:
                    return posts_from_bootstrap
            
            # Also check in initialState or other common patterns
            initial_state = page_props.get('initialState', {})
            if initial_state:
                posts_from_state = self._parse_bootstrap_data(initial_state)
                if posts_from_state:
                    return posts_from_state
                    
        except Exception as e:
            pass
        
        return posts
    
    def _parse_bootstrap_data(self, data: dict) -> List[Post]:
        """Parse posts from Patreon bootstrap JSON data."""
        posts = []
        
        try:
            # Navigate the JSON structure to find posts
            # Structure varies, but typically: data -> included -> posts
            if 'data' in data:
                for item in data.get('data', []):
                    if isinstance(item, dict) and item.get('type') == 'post':
                        post = self._create_post_from_json(item, data.get('included', []))
                        if post:
                            posts.append(post)
            
            # Also check included array
            if 'included' in data:
                for item in data.get('included', []):
                    if isinstance(item, dict) and item.get('type') == 'post':
                        post = self._create_post_from_json(item, data.get('included', []))
                        if post:
                            posts.append(post)
        
        except Exception as e:
            print(f"  Warning: Error parsing bootstrap data: {e}")
        
        return posts
    
    def _create_post_from_json(self, post_data: dict, included: list) -> Optional[Post]:
        """Create a Post object from JSON data."""
        try:
            attributes = post_data.get('attributes', {})
            
            title = attributes.get('title', 'Untitled')
            content = attributes.get('content', '') or ''
            url = attributes.get('url', '') or f"https://www.patreon.com/posts/{post_data.get('id', '')}"
            published_date = attributes.get('published_at', '')
            
            # Extract images
            images = []
            if 'image' in attributes and attributes['image']:
                if isinstance(attributes['image'], dict):
                    images.append(attributes['image'].get('url', ''))
                elif isinstance(attributes['image'], str):
                    images.append(attributes['image'])
            
            return Post(
                title=title,
                content=content,
                url=url,
                published_date=published_date,
                images=images
            )
        except Exception as e:
            return None
    
    def _extract_posts_from_html(self, soup: BeautifulSoup) -> List[Post]:
        """Fallback: Extract posts from HTML structure."""
        posts = []
        
        # Look for common post containers - Patreon uses data-tag attributes
        post_elements = soup.find_all('div', attrs={'data-tag': 'post-card'})
        
        print(f"  Found {len(post_elements)} post cards in HTML")
        
        for elem in post_elements:
            try:
                # Extract title - look for heading elements
                title = 'Untitled'
                
                # Try various selectors for title
                title_elem = elem.find('span', attrs={'data-tag': 'post-title'})
                if not title_elem:
                    title_elem = elem.find('h2')
                if not title_elem:
                    # Look for any heading
                    for heading in ['h1', 'h2', 'h3', 'h4']:
                        title_elem = elem.find(heading)
                        if title_elem:
                            break
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                
                # Extract link
                url = ''
                link_elem = elem.find('a', href=re.compile(r'/posts/'))
                if link_elem:
                    url = link_elem.get('href', '')
                    if url and not url.startswith('http'):
                        url = 'https://www.patreon.com' + url
                
                # If we still don't have a title, try to extract from any text content
                if title == 'Untitled':
                    # Look for the largest text block
                    text_spans = elem.find_all('span')
                    for span in text_spans:
                        text = span.get_text(strip=True)
                        if len(text) > 10 and len(text) < 200:  # Reasonable title length
                            title = text
                            break
                
                # Extract preview content
                content = str(elem)
                
                if url:
                    posts.append(Post(
                        title=title,
                        content=content,
                        url=url,
                    ))
                    
            except Exception as e:
                print(f"  Warning: Error parsing post card: {e}")
                continue
        
        return posts
    
    def get_post_content(self, post_url: str) -> Optional[Post]:
        """
        Fetch detailed content for a specific post.
        
        Args:
            post_url: URL to the post
            
        Returns:
            Post object with full content
        """
        try:
            response = self.session.get(post_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title = self._extract_title(soup)
            
            # Extract content
            content = self._extract_content(soup)
            
            # Extract images
            images = self._extract_images(soup)
            
            # Extract publish date
            published_date = self._extract_date(soup)
            
            return Post(
                title=title,
                content=content,
                url=post_url,
                published_date=published_date,
                images=images
            )
            
        except requests.RequestException as e:
            print(f"✗ Error fetching post {post_url}: {e}")
            return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract post title from page."""
        # Try various selectors
        title_elem = soup.find('h1')
        if title_elem:
            return title_elem.get_text(strip=True)
        
        # Fallback to meta tags
        og_title = soup.find('meta', property='og:title')
        if og_title:
            return og_title.get('content', 'Untitled')
        
        return 'Untitled'
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract post content from page."""
        # Look for common content containers
        # This will need adjustment based on actual page structure
        content_selectors = [
            {'data-tag': 'post-content'},
            {'class': 'post-content'},
            {'class': 'post-body'},
        ]
        
        for selector in content_selectors:
            content_elem = soup.find('div', selector)
            if content_elem:
                return str(content_elem)
        
        # Fallback: try to find main content area
        main = soup.find('main')
        if main:
            return str(main)
        
        return ''
    
    def _extract_images(self, soup: BeautifulSoup) -> List[str]:
        """Extract image URLs from post."""
        images = []
        
        # Find all images in content
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and not src.startswith('data:'):
                images.append(src)
        
        return images
    
    def _extract_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from post."""
        # Try to find date in meta tags
        time_elem = soup.find('time')
        if time_elem:
            return time_elem.get('datetime') or time_elem.get_text(strip=True)
        
        return None
    
    def download_image(self, image_url: str, save_path: Path) -> bool:
        """
        Download an image from URL.
        
        Args:
            image_url: URL of the image
            save_path: Path to save the image
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.session.get(image_url, stream=True)
            response.raise_for_status()
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
            
        except requests.RequestException as e:
            print(f"✗ Error downloading image {image_url}: {e}")
            return False
