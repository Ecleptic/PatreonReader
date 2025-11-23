"""Patreon authentication using Selenium for browser automation."""

import time
import pickle
import json
from pathlib import Path
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from config import Config


class PatreonAuthSelenium:
    """Handle Patreon authentication using Selenium."""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        self.authenticated = False
        self.cookies_file = Config.CACHE_DIR / 'patreon_cookies.pkl'
    
    def _init_driver(self):
        """Initialize Selenium WebDriver."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={Config.USER_AGENT}')
        
        # Enable performance logging to capture network requests
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        # Initialize driver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
    
    def login(self, email: Optional[str] = None, password: Optional[str] = None, 
              use_cached: bool = True) -> bool:
        """
        Login to Patreon using Selenium.
        
        Args:
            email: Patreon email (uses config if not provided)
            password: Patreon password (uses config if not provided)
            use_cached: Try to use cached cookies first
            
        Returns:
            True if login successful, False otherwise
        """
        email = email or Config.PATREON_EMAIL
        password = password or Config.PATREON_PASSWORD
        
        if not email or not password:
            raise ValueError("Email and password are required")
        
        # Initialize driver
        if not self.driver:
            self._init_driver()
        
        try:
            # Try cached cookies first
            if use_cached and self._load_cookies():
                print("  Using cached session...")
                self.driver.get('https://www.patreon.com/home')
                time.sleep(2)
                
                # Check if still logged in
                if self._is_logged_in():
                    self.authenticated = True
                    print("✓ Successfully authenticated with Patreon (cached session)")
                    return True
                else:
                    print("  Cached session expired, logging in fresh...")
            
            # Fresh login
            print("  Opening login page...")
            self.driver.get('https://www.patreon.com/login')
            time.sleep(4)  # Wait for page to fully load
            
            # Wait for and enter email
            print("  Entering email...")
            try:
                email_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]'))
                )
                email_field.clear()
                email_field.send_keys(email)
                time.sleep(2)
                
                # Click continue button to reveal password field
                print("  Continuing to password...")
                continue_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))
                )
                continue_button.click()
                time.sleep(3)  # Wait for password field to appear
                
                # Enter password
                print("  Entering password...")
                password_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
                )
                password_field.clear()
                password_field.send_keys(password)
                time.sleep(1)
                
            except Exception as e:
                print(f"  Error during form interaction: {e}")
                print("  Saving page source for debugging...")
                with open(Config.CACHE_DIR / 'login_error.html', 'w') as f:
                    f.write(self.driver.page_source)
                raise
            
            # Submit form
            print("  Submitting login form...")
            submit_button = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit_button.click()
            
            # Wait for redirect (either to home or 2FA page)
            time.sleep(5)
            
            # Check for 2FA
            current_url = self.driver.current_url
            if '2fa' in current_url.lower() or 'verify' in current_url.lower():
                print("\n⚠ 2FA detected. Please complete 2FA manually in the browser window.")
                print("  Waiting for 2FA completion (60 seconds)...")
                time.sleep(60)
            
            # Verify login
            if self._is_logged_in():
                self.authenticated = True
                self._save_cookies()
                print("✓ Successfully authenticated with Patreon")
                return True
            else:
                print("✗ Login failed: Could not verify authentication")
                return False
                
        except Exception as e:
            print(f"✗ Login error: {e}")
            return False
    
    def _is_logged_in(self) -> bool:
        """Check if currently logged in to Patreon."""
        try:
            # Check for logged-in indicators
            current_url = self.driver.current_url
            if 'login' in current_url.lower():
                return False
            
            # Look for user menu or profile icon
            try:
                self.driver.find_element(By.CSS_SELECTOR, '[data-tag="user-menu"]')
                return True
            except:
                pass
            
            # Check cookies
            cookies = self.driver.get_cookies()
            return any('session' in cookie.get('name', '').lower() for cookie in cookies)
            
        except:
            return False
    
    def _save_cookies(self):
        """Save session cookies to file."""
        try:
            Config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cookies = self.driver.get_cookies()
            with open(self.cookies_file, 'wb') as f:
                pickle.dump(cookies, f)
        except Exception as e:
            print(f"  Warning: Could not save cookies: {e}")
    
    def _load_cookies(self) -> bool:
        """Load session cookies from file."""
        try:
            if not self.cookies_file.exists():
                return False
            
            self.driver.get('https://www.patreon.com')
            time.sleep(1)
            
            with open(self.cookies_file, 'rb') as f:
                cookies = pickle.load(f)
            
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except:
                    pass
            
            return True
            
        except Exception as e:
            return False
    
    def get_page_source(self, url: str) -> str:
        """Get page source for a URL."""
        if not self.authenticated:
            raise RuntimeError("Not authenticated. Call login() first.")
        
        self.driver.get(url)
        time.sleep(3)  # Wait for dynamic content
        
        # Scroll and click "Load more" buttons
        print("  Loading all posts...")
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        no_change_count = 0
        total_scrolls = 0
        load_more_clicks = 0
        max_total_scrolls = 200  # Maximum total scrolls
        max_load_more_clicks = 50  # Maximum Load More button clicks
        
        while total_scrolls < max_total_scrolls:
            # First, try to find and click "Load more" / "Show more" buttons
            try:
                load_more_selectors = [
                    '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "show more")]',
                    '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "load more")]',
                    '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "show more")]',
                    '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "load more")]',
                ]
                
                button_found = False
                for selector in load_more_selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        for elem in elements:
                            if elem.is_displayed() and elem.is_enabled() and load_more_clicks < max_load_more_clicks:
                                # Scroll into view
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                time.sleep(0.5)
                                elem.click()
                                load_more_clicks += 1
                                print(f"    Clicked 'Load more' button ({load_more_clicks})")
                                time.sleep(2)  # Wait for content to load
                                button_found = True
                                no_change_count = 0  # Reset since we loaded more
                                break
                    except:
                        continue
                    if button_found:
                        break
            except:
                pass
            
            # Scroll down
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)  # Wait for content to load
            
            # Calculate new height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            
            if new_height == last_height:
                no_change_count += 1
                # Give it more chances - sometimes Patreon is slow to load
                if no_change_count >= 5:
                    print(f"    No more content after {total_scrolls} scrolls and {load_more_clicks} button clicks")
                    break
            else:
                no_change_count = 0
            
            last_height = new_height
            total_scrolls += 1
            
            # Every 10 scrolls, print progress
            if total_scrolls % 10 == 0:
                # Count post cards currently visible
                try:
                    post_count = len(self.driver.find_elements(By.CSS_SELECTOR, '[data-tag="post-card"]'))
                    print(f"    Scrolled {total_scrolls} times, clicked {load_more_clicks} buttons, {post_count} posts visible")
                except:
                    print(f"    Scrolled {total_scrolls} times, clicked {load_more_clicks} buttons")
        
        # Final count
        try:
            post_count = len(self.driver.find_elements(By.CSS_SELECTOR, '[data-tag="post-card"]'))
            print(f"  Finished loading - {post_count} posts found")
        except:
            print(f"  Finished loading")
        
        return self.driver.page_source
    
    def get_network_requests(self) -> list:
        """Get network requests (for debugging API calls)."""
        if not self.driver:
            return []
        
        try:
            logs = self.driver.get_log('performance')
            return logs
        except:
            return []
    
    def get_api_post_urls(self) -> list:
        """Extract API URLs from performance logs that contain post data."""
        if not self.driver:
            return []
        
        try:
            logs = self.driver.get_log('performance')
            api_urls = []
            
            for entry in logs:
                try:
                    log = json.loads(entry['message'])['message']
                    
                    # Look for API requests
                    if log.get('method') == 'Network.requestWillBeSent':
                        url = log['params']['request']['url']
                        # Patreon API endpoints for posts
                        if '/api/posts' in url or '/api/campaigns' in url and 'include=posts' in url:
                            api_urls.append(url)
                except:
                    continue
            
            return list(set(api_urls))  # Remove duplicates
        except Exception as e:
            print(f"  Warning: Could not get API URLs: {e}")
            return []
    
    def get_hero_image_url(self) -> Optional[str]:
        """
        Extract the hero/cover image URL from the current page.
        
        Returns:
            URL of the hero image or None
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Look for images from patreonusercontent.com with campaign ID
            # These are typically the hero/banner images
            img_tags = soup.find_all('img')
            for img in img_tags:
                src = img.get('src', '')
                # Look for campaign images with larger dimensions (1920w typically)
                if 'patreonusercontent.com' in src and '/campaign/' in src and 'eyJ3IjoxOTIw' in src:
                    return src
            
            # Fallback: look in picture elements
            pictures = soup.find_all('picture')
            for picture in pictures:
                # Get the source with highest resolution
                sources = picture.find_all('source')
                for source in sources:
                    srcset = source.get('srcset', '')
                    if 'patreonusercontent.com' in srcset and '/campaign/' in srcset:
                        # Extract the URL from srcset
                        url = srcset.split()[0] if ' ' in srcset else srcset
                        if 'eyJ3IjoxOTIw' in url:  # 1920w image
                            return url
                
                # Check img inside picture
                img = picture.find('img')
                if img:
                    src = img.get('src', '')
                    if 'patreonusercontent.com' in src and '/campaign/' in src:
                        return src
            
            return None
        except Exception as e:
            print(f"  Warning: Could not extract hero image: {e}")
            return None
    
    def download_hero_image(self, output_path: Path) -> bool:
        """
        Download the hero image from the current page.
        
        Args:
            output_path: Path to save the image
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = self.get_hero_image_url()
            if not url:
                return False
            
            import requests
            
            # Use the same session cookies
            session = requests.Session()
            for cookie in self.driver.get_cookies():
                session.cookies.set(cookie['name'], cookie['value'])
            
            response = session.get(url, timeout=30)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            return True
        except Exception as e:
            print(f"  Warning: Could not download hero image: {e}")
            return False
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def __del__(self):
        """Cleanup on deletion."""
        self.close()
