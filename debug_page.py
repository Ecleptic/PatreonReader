#!/usr/bin/env python3
"""Debug script to inspect Patreon page structure."""

import sys
from patreon_auth_selenium import PatreonAuthSelenium
from config import Config

def main(url):
    Config.validate()
    
    auth = PatreonAuthSelenium(headless=True)
    if not auth.login():
        print("Login failed")
        return
    
    print(f"Fetching {url}...")
    page_source = auth.get_page_source(url)
    
    # Save to file
    output_file = Config.CACHE_DIR / 'debug_page.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(page_source)
    
    print(f"Saved page source to {output_file}")
    print(f"File size: {len(page_source)} bytes")
    
    # Try to find JSON data
    if '__NEXT_DATA__' in page_source:
        print("✓ Found __NEXT_DATA__")
    if 'window.patreon' in page_source:
        print("✓ Found window.patreon")
    
    auth.close()

if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.patreon.com/c/example-creator/posts'
    main(url)
