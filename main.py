#!/usr/bin/env python3
"""
Main CLI interface for Patreon to EPUB converter.
"""

import sys
import click
from pathlib import Path
from config import Config
from patreon_auth_selenium import PatreonAuthSelenium
from patreon_scraper import PatreonScraper
from patreon_api import PatreonAPIClient
from chapter_detector import ChapterDetector
from epub_generator import EpubGenerator, EpubUpdater


@click.command()
@click.argument('creator_url')
@click.option('--update', is_flag=True, help='Update existing EPUB files with new chapters')
@click.option('--book-title', help='Specify book title (for creators without clear patterns)')
@click.option('--series-name', help='Series name to use for volume-based books (e.g., "Beware of Chicken")')
@click.option('--author-pattern', help='Custom regex pattern for chapter detection')
@click.option('--limit', type=int, help='Limit number of posts to fetch')
@click.option('--max-load-more', type=int, default=50, help='Maximum times to click "Load more" (default: 50)')
@click.option('--output-dir', type=click.Path(), help='Output directory for EPUB files')
@click.option('--no-headless', is_flag=True, help='Show browser window (for debugging)')
def main(creator_url, update, book_title, series_name, author_pattern, limit, max_load_more, output_dir, no_headless):
    """
    Download and convert Patreon posts to EPUB format.
    
    CREATOR_URL: URL to the Patreon creator's posts page
    (e.g., https://www.patreon.com/c/lunadea/posts)
    """
    auth = None
    try:
        # Validate configuration
        Config.validate()
        
        # Override output directory if specified
        if output_dir:
            Config.OUTPUT_DIR = Path(output_dir)
            Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        print("=" * 60)
        print("Patreon to EPUB Converter")
        print("=" * 60)
        
        # Extract creator name from URL
        creator_name = extract_creator_name(creator_url)
        print(f"\nCreator: {creator_name}")
        
        # Step 1: Authenticate
        print("\n[1/5] Authenticating with Patreon...")
        auth = PatreonAuthSelenium(headless=not no_headless)
        if not auth.login():
            print("✗ Authentication failed. Please check your credentials in .env")
            sys.exit(1)
        
        # Step 2: Scrape posts
        print(f"\n[2/5] Fetching posts from {creator_url}...")
        
        # Try API approach first
        api_client = PatreonAPIClient(auth)
        campaign_id, user_id = api_client.get_campaign_id_from_url(creator_url, auth_driver=auth)
        
        # Get the actual creator display name from the page
        creator_display_name = get_creator_display_name(auth)
        if creator_display_name:
            creator_name = creator_display_name
        else:
            creator_name = extract_creator_name(creator_url)
        
        posts = []
        if campaign_id:
            print(f"  Using Patreon API (Campaign: {campaign_id}, User: {user_id or 'N/A'})")
            posts = api_client.get_campaign_posts(campaign_id, user_id=user_id, limit=limit)
        
        # Fallback to scraping if API fails
        if not posts:
            print(f"  Falling back to HTML scraping...")
            scraper = PatreonScraper(auth)
            posts = scraper.get_creator_posts(creator_url, limit=limit, max_load_more=max_load_more)
        
        if not posts:
            print("✗ No posts found.")
            print("\n⚠ Possible reasons:")
            print("  1. The creator has no public posts")
            print("  2. You need to be a patron to view posts")
            print("  3. The page structure has changed")
            auth.close()
            sys.exit(1)
        
        # Step 3: Detect books and chapters
        print(f"\n[3/5] Detecting books and chapters...")
        
        # Debug: Show first few post titles
        if posts:
            print(f"\n  Sample post titles:")
            for i, post in enumerate(posts[:5]):
                print(f"    {i+1}. {post.title}")
        
        detector = ChapterDetector(creator_name, custom_pattern=author_pattern, series_name=series_name, creator_url=creator_url)
        books = detector.organize_posts(posts, default_book_title=book_title)
        
        if not books:
            print(f"\n✗ No books detected.")
            print(f"  Try specifying --book-title \"Book Name\" to group all posts")
            print(f"  Or check the post titles above to create a custom pattern")
            auth.close()
            sys.exit(1)
        
        print(f"✓ Detected {len(books)} book(s):")
        for book_title_key, book in books.items():
            print(f"  - {book_title_key}: {len(book.chapters)} chapter(s)")
            last_chapter = book.get_last_chapter_number()
            if last_chapter:
                print(f"    Last chapter: {last_chapter}")
        
        # Step 4: Fetch cover image
        print(f"\n[4/6] Fetching cover image...")
        cover_path = api_client.get_hero_image(creator_url, auth)
        
        # Step 5: Generate or update EPUBs
        if update:
            print(f"\n[5/6] Updating existing EPUB files...")
            updater = EpubUpdater()
            
            for book_title_key, book in books.items():
                epub_filename = EpubGenerator(Config.OUTPUT_DIR)._sanitize_filename(book_title_key) + '.epub'
                epub_path = Config.OUTPUT_DIR / epub_filename
                
                if epub_path.exists():
                    # Read existing EPUB
                    existing_book = updater.read_epub(epub_path)
                    
                    # Find new chapters
                    new_chapters = detector.find_new_chapters(
                        existing_book.chapters,
                        posts,
                        book_title_key
                    )
                    
                    if new_chapters:
                        print(f"\n  {book_title_key}:")
                        print(f"    Found {len(new_chapters)} new chapter(s)")
                        updater.append_chapters(epub_path, new_chapters)
                    else:
                        print(f"\n  {book_title_key}:")
                        print(f"    No new chapters found")
                else:
                    print(f"\n  {book_title_key}:")
                    print(f"    EPUB not found, creating new file...")
                    generator = EpubGenerator(Config.OUTPUT_DIR)
                    generator.create_epub(book, cover_image_path=cover_path)
        else:
            print(f"\n[5/6] Generating EPUB files...")
            generator = EpubGenerator(Config.OUTPUT_DIR)
            
            for book_title_key, book in books.items():
                generator.create_epub(book, cover_image_path=cover_path)
        
        # Step 5: Complete
        print(f"\n[6/6] Complete!")
        print(f"\n✓ EPUB files saved to: {Config.OUTPUT_DIR}")
        print("\n" + "=" * 60)
        
        # Close browser
        auth.close()
        
    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nMake sure you have:")
        print("  1. Created a .env file (copy from .env.example)")
        print("  2. Set PATREON_EMAIL and PATREON_PASSWORD")
        if auth:
            auth.close()
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        if auth:
            auth.close()
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        if auth:
            auth.close()
        sys.exit(1)


def extract_creator_name(url: str) -> str:
    """Extract creator name from Patreon URL."""
    import re
    
    # Pattern: https://www.patreon.com/c/CREATOR/posts
    match = re.search(r'/c/([^/]+)', url)
    if match:
        return match.group(1).title()
    
    # Fallback pattern: https://www.patreon.com/CREATOR
    match = re.search(r'patreon\.com/([^/]+)', url)
    if match:
        creator = match.group(1)
        # Remove 'posts' if it's in the URL
        if creator == 'posts':
            return 'Unknown Creator'
        return creator.title()
    
    return 'Unknown Creator'


def get_creator_display_name(auth_driver) -> str:
    """Get the actual creator display name from the page."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(auth_driver.driver.page_source, 'html.parser')
        
        # Find the h1 with creator name
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
            if name and name.lower() != 'patreon':
                return name
        
        # Fallback: look for profile name span
        spans = soup.find_all('span', {'data-tag': 'profile-name'})
        for span in spans:
            name = span.get_text(strip=True)
            if name:
                return name
    except:
        pass
    
    return None


if __name__ == '__main__':
    main()
