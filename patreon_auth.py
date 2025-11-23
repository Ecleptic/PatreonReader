"""Patreon authentication module."""

import requests
import json
from typing import Optional
from config import Config


class PatreonAuth:
    """Handle Patreon authentication and session management."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': Config.USER_AGENT,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        self.authenticated = False
    
    def login(self, email: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Login to Patreon using email and password.
        
        Args:
            email: Patreon email (uses config if not provided)
            password: Patreon password (uses config if not provided)
            
        Returns:
            True if login successful, False otherwise
        """
        email = email or Config.PATREON_EMAIL
        password = password or Config.PATREON_PASSWORD
        
        if not email or not password:
            raise ValueError("Email and password are required")
        
        # Get the login page first to establish session and get cookies
        try:
            print("  Establishing session...")
            login_page = self.session.get(
                'https://www.patreon.com/login',
                headers={
                    'User-Agent': Config.USER_AGENT,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            
            # Extract CSRF token if present
            csrf_token = None
            for cookie in self.session.cookies:
                if 'csrf' in cookie.name.lower():
                    csrf_token = cookie.value
                    break
            
            # Prepare login payload
            login_data = {
                'data': {
                    'type': 'user',
                    'attributes': {
                        'email': email,
                        'password': password
                    }
                }
            }
            
            # Build headers
            headers = {
                'Referer': 'https://www.patreon.com/login',
                'Origin': 'https://www.patreon.com',
                'User-Agent': Config.USER_AGENT,
                'Accept': 'application/json',
                'Content-Type': 'application/vnd.api+json',
            }
            
            if csrf_token:
                headers['X-CSRF-Token'] = csrf_token
            
            print("  Attempting login...")
            # Attempt login
            response = self.session.post(
                Config.PATREON_LOGIN_URL,
                json=login_data,
                headers=headers
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'data' in data and 'id' in data['data']:
                        self.authenticated = True
                        print("✓ Successfully authenticated with Patreon")
                        return True
                except json.JSONDecodeError:
                    pass
            
            # Even if the API returns an error, check if session cookies indicate we're logged in
            if any('session' in cookie.name.lower() for cookie in self.session.cookies):
                self.authenticated = True
                print("✓ Successfully authenticated with Patreon (via session)")
                return True
            
            print(f"✗ Login failed: Status {response.status_code}")
            if response.status_code == 403:
                print("  Note: 403 may indicate CSRF protection or rate limiting")
                print("  The scraper may need Selenium/Playwright for full browser automation")
            return False
            
        except requests.RequestException as e:
            print(f"✗ Login error: {e}")
            return False
    
    def get_session(self) -> requests.Session:
        """Get the authenticated session."""
        if not self.authenticated:
            raise RuntimeError("Not authenticated. Call login() first.")
        return self.session
    
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self.authenticated
