#!/usr/bin/env python3
"""Extract and analyze __NEXT_DATA__ from saved page."""

import json
import re
from pathlib import Path

# Read the saved page
page_file = Path('cache/debug_page.html')
with open(page_file, 'r', encoding='utf-8') as f:
    html = f.read()

# Find __NEXT_DATA__
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.DOTALL)

if match:
    json_str = match.group(1)
    data = json.loads(json_str)
    
    # Save to formatted JSON
    with open('cache/next_data.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print("✓ Extracted __NEXT_DATA__ to cache/next_data.json")
    
    # Try to find posts
    def find_posts(obj, path=""):
        """Recursively search for post data."""
        if isinstance(obj, dict):
            # Check if this looks like a post
            if 'title' in obj and 'type' in obj:
                if obj.get('type') == 'post':
                    print(f"\nFound post at {path}:")
                    print(f"  Title: {obj.get('title', 'N/A')[:100]}")
                    print(f"  ID: {obj.get('id', 'N/A')}")
            
            for key, value in obj.items():
                find_posts(value, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                find_posts(item, f"{path}[{i}]")
    
    print("\nSearching for post data...")
    find_posts(data)
    
else:
    print("✗ Could not find __NEXT_DATA__")
