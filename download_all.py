#!/usr/bin/env python3
"""Download all books from the books file."""

import subprocess
import sys
from pathlib import Path

# Series name mappings (optional - add as needed)
SERIES_NAMES = {
    'Zogarth': 'Primal Hunter',
    'u48733767': 'Beware of Chicken',
}

def read_books_file():
    """Read URLs from the books file."""
    books_file = Path(__file__).parent / 'books'
    
    if not books_file.exists():
        print("Error: 'books' file not found")
        sys.exit(1)
    
    urls = []
    with open(books_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith('#'):
                urls.append(line)
    
    return urls

def extract_creator_from_url(url):
    """Extract creator name from URL for series mapping."""
    import re
    
    # Pattern: https://www.patreon.com/c/CREATOR/posts
    match = re.search(r'/c/([^/]+)', url)
    if match:
        return match.group(1)
    
    # Fallback pattern: https://www.patreon.com/CREATOR
    match = re.search(r'patreon\.com/([^/]+)', url)
    if match:
        creator = match.group(1)
        if creator != 'posts':
            return creator
    
    return None

def download_book(url):
    """Download a book from the given URL."""
    print(f"\n{'='*70}")
    print(f"Downloading: {url}")
    print('='*70)
    
    # Check if we have a series name mapping
    creator = extract_creator_from_url(url)
    series_name = SERIES_NAMES.get(creator) if creator else None
    
    # Build command
    cmd = ['python3', 'main.py', url]
    if series_name:
        cmd.extend(['--series-name', series_name])
    
    # Run the download
    try:
        result = subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error downloading {url}: {e}")
        return False

def main():
    """Main function."""
    urls = read_books_file()
    
    if not urls:
        print("No URLs found in 'books' file")
        sys.exit(1)
    
    print(f"Found {len(urls)} book(s) to download")
    
    successful = 0
    failed = 0
    
    for url in urls:
        if download_book(url):
            successful += 1
        else:
            failed += 1
    
    print(f"\n{'='*70}")
    print(f"Download Summary:")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print('='*70)

if __name__ == '__main__':
    main()
