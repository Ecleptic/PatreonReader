"""Direct Patreon API client using authenticated session."""

import requests
import json
from typing import List, Optional, Dict
from pathlib import Path
from bs4 import BeautifulSoup
from patreon_scraper import Post
from config import Config


class PatreonAPIClient:
    """Use Patreon's API directly to fetch posts."""
    
    def __init__(self, auth_selenium):
        """
        Initialize with authenticated Selenium session.
        
        Args:
            auth_selenium: PatreonAuthSelenium instance with active session
        """
        self.session = requests.Session()
        
        # Copy cookies from Selenium to requests
        if auth_selenium.driver:
            for cookie in auth_selenium.driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'])
        
        # Set headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
    
    def get_campaign_posts(self, campaign_id: str, user_id: Optional[str] = None, limit: Optional[int] = None) -> List[Post]:
        """
        Fetch posts from a campaign using the API.
        
        Args:
            campaign_id: The campaign ID
            user_id: Optional user ID for accessible_by filter  
            limit: Optional limit on posts to fetch
            
        Returns:
            List of Post objects
        """
        posts = []
        cursor = None
        page = 0
        
        print(f"  Fetching posts via API...")
        
        while True:
            page += 1
            
            # Build API URL with proper filters
            url = f"https://www.patreon.com/api/posts"
            params = {
                'include': 'campaign,images,media,user',
                'fields[post]': 'change_visibility_at,comment_count,content,current_user_can_delete,current_user_can_view,current_user_has_liked,embed,image,is_paid,like_count,post_file,published_at,patreon_url,post_type,title,url',
                'fields[campaign]': 'currency,show_audio_post_download_links,avatar_photo_url,is_nsfw,is_monthly,name,url',
                'fields[media]': 'id,image_urls,download_url,metadata,file_name',
                'filter[campaign_id]': campaign_id,
                'filter[is_draft]': 'false',
                'sort': '-published_at',
                'json-api-use-default-includes': 'false',
                'json-api-version': '1.0',
            }
            
            if user_id:
                params['filter[accessible_by_user_id]'] = user_id
            
            if cursor:
                params['page[cursor]'] = cursor
            
            try:
                response = self.session.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                # Extract posts from response
                if 'data' in data:
                    page_posts = self._parse_api_response(data)
                    posts.extend(page_posts)
                    print(f"    Page {page}: {len(page_posts)} posts (total: {len(posts)})")
                    
                    # Check if we've hit the limit
                    if limit and len(posts) >= limit:
                        posts = posts[:limit]
                        break
                    
                    # Check for next page
                    if 'links' in data and 'next' in data['links'] and data['links']['next']:
                        # Extract cursor from next URL
                        next_url = data['links']['next']
                        if 'page%5Bcursor%5D=' in next_url:
                            cursor = next_url.split('page%5Bcursor%5D=')[1].split('&')[0]
                        elif 'page[cursor]=' in next_url:
                            from urllib.parse import urlparse, parse_qs
                            parsed = urlparse(next_url)
                            query = parse_qs(parsed.query)
                            cursor = query.get('page[cursor]', [None])[0]
                            if not cursor:
                                break
                        else:
                            print(f"    No cursor found in next URL, stopping pagination")
                            break
                    else:
                        print(f"    No more pages available")
                        break
                else:
                    break
                    
            except Exception as e:
                print(f"    API Error on page {page}: {e}")
                break
        
        return posts
    
    def _parse_api_response(self, data: Dict) -> List[Post]:
        """Parse API response into Post objects."""
        posts = []
        
        # Build included items lookup
        included = {}
        if 'included' in data:
            for item in data['included']:
                key = f"{item['type']}:{item['id']}"
                included[key] = item
        
        for item in data.get('data', []):
            if item.get('type') == 'post':
                try:
                    attrs = item.get('attributes', {})
                    
                    title = attrs.get('title', 'Untitled')
                    content = attrs.get('content', '')
                    url = attrs.get('url', '') or attrs.get('patreon_url', '')
                    published_date = attrs.get('published_at', '')
                    
                    # Extract images
                    images = []
                    if attrs.get('image'):
                        img_data = attrs['image']
                        if isinstance(img_data, dict) and 'url' in img_data:
                            images.append(img_data['url'])
                    
                    # Check for media attachments in relationships
                    relationships = item.get('relationships', {})
                    if 'images' in relationships:
                        for img_ref in relationships['images'].get('data', []):
                            img_key = f"{img_ref['type']}:{img_ref['id']}"
                            if img_key in included:
                                img_item = included[img_key]
                                img_attrs = img_item.get('attributes', {})
                                if 'image_urls' in img_attrs:
                                    images.extend(img_attrs['image_urls'].values())
                    
                    post = Post(
                        title=title,
                        content=content,
                        url=url,
                        published_date=published_date,
                        images=images
                    )
                    posts.append(post)
                    
                except Exception as e:
                    print(f"    Warning: Error parsing post: {e}")
                    continue
        
        return posts
    
    def get_campaign_id_from_url(self, url: str, auth_driver=None) -> tuple:
        """
        Extract campaign ID and user ID from a Patreon URL.
        
        Args:
            url: Patreon creator URL
            auth_driver: Optional PatreonAuthSelenium instance to extract from performance logs
            
        Returns:
            Tuple of (campaign_id, user_id) or (None, None)
        """
        try:
            # Get user ID from stream_user_token cookie
            import json
            from urllib.parse import unquote, parse_qs, urlparse
            import time
            
            user_id = None
            stream_token = self.session.cookies.get('stream_user_token', '')
            if stream_token:
                try:
                    # URL decode and parse JSON
                    decoded = unquote(stream_token)
                    token_data = json.loads(decoded)
                    user_id = token_data.get('id')
                except:
                    pass
            
            campaign_id = None
            
            # If we have the auth driver, extract campaign ID from performance logs
            if auth_driver and auth_driver.driver:
                # Navigate to the page to trigger API calls
                auth_driver.driver.get(url)
                time.sleep(2)  # Wait for API calls
                
                api_urls = auth_driver.get_api_post_urls()
                if api_urls:
                    # Find the /api/posts URL with campaign_id filter
                    posts_url = None
                    for api_url in api_urls:
                        if '/api/posts?' in api_url and 'filter[campaign_id]' in api_url:
                            posts_url = api_url
                            break
                    
                    if posts_url:
                        # Parse the URL to get campaign_id
                        parsed = urlparse(posts_url)
                        params = parse_qs(parsed.query)
                        if 'filter[campaign_id]' in params:
                            campaign_id = params['filter[campaign_id]'][0]
            
            # Fallback: try to get from page HTML
            if not campaign_id:
                response = self.session.get(url)
                response.raise_for_status()
                
                # Look for campaign ID in the page
                import re
                
                # Find campaign ID from filter parameter in API call
                campaign_match = re.search(r'filter\[campaign_id\]=(\d+)', response.text)
                campaign_id = campaign_match.group(1) if campaign_match else None
                
                # Fallback: try JSON data
                if not campaign_id:
                    json_match = re.search(r'"campaign".*?"id":"(\d+)"', response.text)
                    if json_match:
                        campaign_id = json_match.group(1)
            
            return (campaign_id, user_id)
                
        except Exception as e:
            print(f"  Error extracting IDs: {e}")
        
        return (None, None)
    
    def get_hero_image(self, creator_url: str, auth_driver) -> Optional[Path]:
        """
        Extract and download the hero banner image from a creator's Patreon page.
        
        Args:
            creator_url: The Patreon creator URL
            auth_driver: Authenticated Selenium driver
            
        Returns:
            Path to downloaded cover image, or None if failed
        """
        try:
            print("  Fetching hero image...")
            
            # Navigate to page if needed
            if auth_driver.driver.current_url != creator_url:
                auth_driver.driver.get(creator_url)
                import time
                time.sleep(5)  # Wait for page load
            
            # Parse page HTML
            soup = BeautifulSoup(auth_driver.driver.page_source, 'html.parser')
            
            # Find hero image by looking for picture elements with campaign images
            # Hero images typically have "campaign" in URL and large width (1920)
            pictures = soup.find_all('picture')
            
            image_url = None
            for picture in pictures:
                img = picture.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Look for campaign images with hero dimensions
                    if 'campaign' in src and ('1920' in src or '1200' in src):
                        image_url = src
                        print(f"  Found hero image: {image_url[:80]}...")
                        break
            
            if not image_url:
                print("  Warning: Could not find hero image")
                return None
            
            # Download image using authenticated session
            response = self.session.get(image_url, stream=True)
            response.raise_for_status()
            
            # Create covers directory
            covers_dir = Path(Config.CACHE_DIR) / 'covers'
            covers_dir.mkdir(exist_ok=True)
            
            # Determine file extension from URL or content-type
            ext = '.jpg'
            if '.png' in image_url:
                ext = '.png'
            elif 'image/png' in response.headers.get('content-type', ''):
                ext = '.png'
            
            # Save with campaign ID as filename (extract from URL)
            import re
            campaign_match = re.search(r'/campaign/(\d+)/', image_url)
            if campaign_match:
                filename = f"{campaign_match.group(1)}{ext}"
            else:
                # Fallback to hash of URL
                filename = f"{hash(creator_url)}{ext}"
            
            cover_path = covers_dir / filename
            
            # Write image
            with open(cover_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"  Downloaded cover to: {cover_path}")
            return cover_path
            
        except Exception as e:
            print(f"  Error downloading hero image: {e}")
            return None
