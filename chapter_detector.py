"""Chapter detection and book organization."""

import re
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from patreon_scraper import Post


class Chapter:
    """Represents a book chapter."""
    
    def __init__(self, title: str, number: Optional[int], content: str, 
                 images: List[str], original_post: Post):
        self.title = title
        self.number = number
        self.content = content
        self.images = images
        self.original_post = original_post
    
    def __repr__(self):
        return f"Chapter(title='{self.title}', number={self.number})"


class Book:
    """Represents a book with multiple chapters."""
    
    def __init__(self, title: str, author: str, publisher_url: str = None):
        self.title = title
        self.author = author
        self.publisher_url = publisher_url
        self.chapters: List[Chapter] = []
    
    def add_chapter(self, chapter: Chapter):
        """Add a chapter to the book."""
        self.chapters.append(chapter)
    
    def sort_chapters(self):
        """Sort chapters by chapter number."""
        # Sort by chapter number, putting chapters without numbers at the end
        self.chapters.sort(key=lambda c: (c.number is None, c.number or 0))
    
    def get_last_chapter_number(self) -> Optional[int]:
        """Get the highest chapter number in the book."""
        chapter_numbers = [c.number for c in self.chapters if c.number is not None]
        return max(chapter_numbers) if chapter_numbers else None
    
    def __repr__(self):
        return f"Book(title='{self.title}', chapters={len(self.chapters)})"


class ChapterDetector:
    """Detect and organize posts into books and chapters."""
    
    # Common patterns for chapter detection
    PATTERNS = [
        # "Book Title: Chapter 5" or "Book Title: Ch 5"
        r'^(.+?):\s*(?:Chapter|Ch\.?)\s*(\d+)',
        # "Book Title - Chapter 5"
        r'^(.+?)\s*-\s*(?:Chapter|Ch\.?)\s*(\d+)',
        # "v7c9" format (volume 7 chapter 9)
        r'^v(\d+)c(\d+)',
        # "Chapter 5: Title" (no book name)
        r'^(?:Chapter|Ch\.?)\s*(\d+)',
        # "Book Title (5)" or "Book Title [5]"
        r'^(.+?)\s*[\(\[](\d+)[\)\]]',
    ]
    
    def __init__(self, author_name: str, custom_pattern: Optional[str] = None, series_name: Optional[str] = None, creator_url: str = None):
        self.author_name = author_name
        self.custom_pattern = custom_pattern
        self.series_name = series_name
        self.creator_url = creator_url
    
    def organize_posts(self, posts: List[Post], default_book_title: Optional[str] = None) -> Dict[str, Book]:
        """
        Organize posts into books and chapters.
        
        Args:
            posts: List of posts to organize
            default_book_title: Default book title if pattern detection fails
            
        Returns:
            Dictionary mapping book titles to Book objects
        """
        books: Dict[str, Book] = {}
        unmatched_posts = []
        
        for post in posts:
            match = self.parse_title(post.title)
            
            if match:
                book_title, chapter_num = match
                
                # Create book if it doesn't exist
                if book_title not in books:
                    books[book_title] = Book(book_title, self.author_name, self.creator_url)
                
                # Create chapter
                chapter = Chapter(
                    title=post.title,
                    number=chapter_num,
                    content=post.content,
                    images=post.images,
                    original_post=post
                )
                
                books[book_title].add_chapter(chapter)
            else:
                unmatched_posts.append(post)
        
        # Handle unmatched posts
        if unmatched_posts and default_book_title:
            if default_book_title not in books:
                books[default_book_title] = Book(default_book_title, self.author_name, self.creator_url)
            
            for post in unmatched_posts:
                chapter = Chapter(
                    title=post.title,
                    number=None,
                    content=post.content,
                    images=post.images,
                    original_post=post
                )
                books[default_book_title].add_chapter(chapter)
        
        # Sort chapters in each book
        for book in books.values():
            book.sort_chapters()
        
        return books
    
    def parse_title(self, title: str) -> Optional[Tuple[str, Optional[int]]]:
        """
        Parse a post title to extract book name and chapter number.
        
        Args:
            title: Post title
            
        Returns:
            Tuple of (book_title, chapter_number) or None if no match
        """
        # Try custom pattern first
        if self.custom_pattern:
            match = re.match(self.custom_pattern, title, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    return (groups[0].strip(), int(groups[1]))
                elif len(groups) == 1:
                    return (title, int(groups[0]))
        
        # Special case for "v7c9" format - combine volume and chapter
        vc_match = re.match(r'^v(\d+)c(\d+)', title, re.IGNORECASE)
        if vc_match:
            volume, chapter = vc_match.groups()
            # Use series name if provided, otherwise author name
            prefix = self.series_name if self.series_name else self.author_name
            return (f"{prefix} - Volume {volume}", int(chapter))
        
        # Try standard patterns
        for pattern in self.PATTERNS:
            match = re.match(pattern, title, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    return (groups[0].strip(), int(groups[1]))
                elif len(groups) == 1:
                    # Pattern matched chapter number only - use series name if provided
                    book_name = self.series_name if self.series_name else f"Untitled Book by {self.author_name}"
                    return (book_name, int(groups[0]))
        
        return None
    
    def detect_books(self, posts: List[Post]) -> List[str]:
        """
        Detect unique book titles from posts.
        
        Args:
            posts: List of posts
            
        Returns:
            List of detected book titles
        """
        book_titles = set()
        
        for post in posts:
            match = self.parse_title(post.title)
            if match:
                book_title, _ = match
                book_titles.add(book_title)
        
        return sorted(book_titles)
    
    def find_new_chapters(self, existing_chapters: List[Chapter], 
                         all_posts: List[Post], book_title: str) -> List[Chapter]:
        """
        Find new chapters that aren't in the existing chapters list.
        
        Args:
            existing_chapters: List of existing chapters
            all_posts: All available posts
            book_title: Book title to filter by
            
        Returns:
            List of new chapters
        """
        # Get existing chapter numbers
        existing_numbers = {c.number for c in existing_chapters if c.number is not None}
        existing_titles = {c.title for c in existing_chapters}
        
        new_chapters = []
        
        for post in all_posts:
            match = self.parse_title(post.title)
            if match:
                detected_book, chapter_num = match
                
                # Check if this post belongs to the target book
                if detected_book == book_title:
                    # Check if it's a new chapter
                    is_new = (
                        (chapter_num is not None and chapter_num not in existing_numbers) or
                        (chapter_num is None and post.title not in existing_titles)
                    )
                    
                    if is_new:
                        chapter = Chapter(
                            title=post.title,
                            number=chapter_num,
                            content=post.content,
                            images=post.images,
                            original_post=post
                        )
                        new_chapters.append(chapter)
        
        # Sort new chapters
        new_chapters.sort(key=lambda c: (c.number is None, c.number or 0))
        
        return new_chapters
