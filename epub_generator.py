"""EPUB generation and management."""

import os
from pathlib import Path
from typing import List, Optional
from ebooklib import epub
from bs4 import BeautifulSoup
import hashlib
from chapter_detector import Book, Chapter


class EpubGenerator:
    """Generate EPUB files from book data."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_epub(self, book: Book, cover_image_path: Optional[Path] = None) -> Path:
        """
        Create an EPUB file from a Book object.
        
        Args:
            book: Book object with chapters
            cover_image_path: Optional path to cover image
            
        Returns:
            Path to the created EPUB file
        """
        # Create EPUB book
        epub_book = epub.EpubBook()
        
        # Set metadata
        epub_book.set_identifier(self._generate_id(book.title))
        epub_book.set_title(book.title)
        epub_book.set_language('en')
        epub_book.add_author(book.author)
        
        # Set publisher as the Patreon URL
        if book.publisher_url:
            epub_book.add_metadata('DC', 'publisher', book.publisher_url)
        
        # Add cover image if provided
        if cover_image_path and cover_image_path.exists():
            with open(cover_image_path, 'rb') as f:
                epub_book.set_cover('cover.jpg', f.read())
        
        # Add chapters
        epub_chapters = []
        spine = ['nav']
        
        for idx, chapter in enumerate(book.chapters):
            epub_chapter = self._create_chapter(chapter, idx)
            epub_book.add_item(epub_chapter)
            epub_chapters.append(epub_chapter)
            spine.append(epub_chapter)
        
        # Add default NCX and Nav files
        epub_book.add_item(epub.EpubNcx())
        epub_book.add_item(epub.EpubNav())
        
        # Define Table of Contents
        epub_book.toc = tuple(epub_chapters)
        
        # Add CSS
        style = self._get_default_css()
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content=style
        )
        epub_book.add_item(nav_css)
        
        # Define spine
        epub_book.spine = spine
        
        # Write EPUB file
        filename = self._sanitize_filename(book.title) + '.epub'
        output_path = self.output_dir / filename
        
        epub.write_epub(output_path, epub_book)
        print(f"✓ Created EPUB: {output_path}")
        
        return output_path
    
    def _create_chapter(self, chapter: Chapter, index: int) -> epub.EpubHtml:
        """Create an EPUB chapter from a Chapter object."""
        # Create chapter
        epub_chapter = epub.EpubHtml(
            title=chapter.title,
            file_name=f'chapter_{index:03d}.xhtml',
            lang='en'
        )
        
        # Process content HTML
        content_html = self._process_content(chapter.content, chapter.images)
        
        # Set chapter content
        chapter_html = f'''
        <html>
        <head>
            <title>{chapter.title}</title>
        </head>
        <body>
            <h1>{chapter.title}</h1>
            {content_html}
        </body>
        </html>
        '''
        
        epub_chapter.content = chapter_html
        
        return epub_chapter
    
    def _process_content(self, content: str, images: List[str]) -> str:
        """Process chapter content HTML, handling images."""
        if not content:
            return '<p>No content available.</p>'
        
        # Parse HTML content
        soup = BeautifulSoup(content, 'html.parser')
        
        # Clean up content (remove scripts, etc.)
        for tag in soup.find_all(['script', 'style']):
            tag.decompose()
        
        return str(soup)
    
    def _get_default_css(self) -> str:
        """Get default CSS for EPUB."""
        return '''
        body {
            font-family: Georgia, serif;
            line-height: 1.6;
            margin: 2em;
        }
        h1 {
            text-align: center;
            margin-bottom: 1em;
            font-size: 2em;
        }
        h2 {
            margin-top: 1.5em;
            font-size: 1.5em;
        }
        p {
            text-indent: 1em;
            margin: 0;
        }
        p:first-of-type {
            text-indent: 0;
        }
        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 1em auto;
        }
        '''
    
    def _generate_id(self, title: str) -> str:
        """Generate a unique ID for the book."""
        return hashlib.md5(title.encode()).hexdigest()
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem."""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename.strip()


class EpubUpdater:
    """Update existing EPUB files with new chapters."""
    
    def __init__(self):
        pass
    
    def read_epub(self, epub_path: Path) -> Book:
        """
        Read an existing EPUB file and extract book data.
        
        Args:
            epub_path: Path to EPUB file
            
        Returns:
            Book object with existing chapters
        """
        book_epub = epub.read_epub(str(epub_path))
        
        # Extract metadata
        title = book_epub.get_metadata('DC', 'title')[0][0] if book_epub.get_metadata('DC', 'title') else 'Unknown'
        author = book_epub.get_metadata('DC', 'creator')[0][0] if book_epub.get_metadata('DC', 'creator') else 'Unknown'
        
        book = Book(title, author)
        
        # Extract chapters
        for item in book_epub.get_items():
            if item.get_type() == 9:  # ITEM_DOCUMENT
                content = item.get_content().decode('utf-8')
                soup = BeautifulSoup(content, 'html.parser')
                
                # Extract chapter title
                h1 = soup.find('h1')
                chapter_title = h1.get_text(strip=True) if h1 else 'Untitled'
                
                # Try to parse chapter number from title
                chapter_num = self._extract_chapter_number(chapter_title)
                
                # Create a dummy Post for the Chapter
                from patreon_scraper import Post
                dummy_post = Post(
                    title=chapter_title,
                    content=str(soup.find('body')) if soup.find('body') else content,
                    url='',
                )
                
                chapter = Chapter(
                    title=chapter_title,
                    number=chapter_num,
                    content=content,
                    images=[],
                    original_post=dummy_post
                )
                
                book.add_chapter(chapter)
        
        return book
    
    def append_chapters(self, epub_path: Path, new_chapters: List[Chapter], 
                       output_path: Optional[Path] = None) -> Path:
        """
        Append new chapters to an existing EPUB.
        
        Args:
            epub_path: Path to existing EPUB
            new_chapters: List of new chapters to append
            output_path: Optional output path (overwrites original if not specified)
            
        Returns:
            Path to updated EPUB
        """
        # Read existing book
        book = self.read_epub(epub_path)
        
        # Add new chapters
        for chapter in new_chapters:
            book.add_chapter(chapter)
        
        # Sort all chapters
        book.sort_chapters()
        
        # Generate new EPUB
        generator = EpubGenerator(epub_path.parent)
        
        # Temporarily change output filename if needed
        if output_path:
            original_output_dir = generator.output_dir
            generator.output_dir = output_path.parent
            result_path = generator.create_epub(book)
            generator.output_dir = original_output_dir
            
            # Rename to desired output path
            if result_path != output_path:
                result_path.rename(output_path)
                result_path = output_path
        else:
            # Overwrite original
            temp_path = epub_path.with_suffix('.epub.tmp')
            
            # Create new EPUB with updated content
            result_path = generator.create_epub(book)
            
            # If the generated file has a different name than expected, handle it
            if result_path != epub_path:
                # Generated file is not where we expect
                if epub_path.exists():
                    epub_path.unlink()  # Remove old file
                result_path.rename(epub_path)  # Rename new file to correct location
                result_path = epub_path
            else:
                # Generated file is at the correct location, nothing to do
                result_path = epub_path
        
        print(f"✓ Added {len(new_chapters)} new chapter(s) to {epub_path.name}")
        
        return result_path
    
    def _extract_chapter_number(self, title: str) -> Optional[int]:
        """Extract chapter number from title."""
        import re
        
        patterns = [
            r'Chapter\s+(\d+)',
            r'Ch\.?\s+(\d+)',
            r'#(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return None
