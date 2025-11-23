# Patreon to EPUB Converter

Download and convert Patreon posts to EPUB format, with support for multiple books per creator and intelligent chapter appending.

## Features

- Download posts from Patreon creators with authentication
- Automatically detect multiple books from post titles
- Convert posts to well-formatted EPUB files
- Append new chapters to existing EPUB files (avoids duplicates)
- Include inline images in EPUB
- Custom pattern matching for different authors

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and add your Patreon credentials:
```bash
cp .env.example .env
```

3. Edit `.env` with your Patreon email and password.

## Usage

### Download and convert all posts from a creator:
```bash
python main.py https://www.patreon.com/c/lunadea/posts
```

### Update existing EPUB with new chapters:
```bash
python main.py https://www.patreon.com/c/lunadea/posts --update
```

### Specify custom book title (for creators without clear patterns):
```bash
python main.py https://www.patreon.com/c/creator/posts --book-title "My Book Title"
```

## Configuration

The tool will automatically detect book titles and chapter numbers from post titles. For Lunadea, it recognizes patterns like:
- "Syl: Chapter 5"
- "Bookbound Bunny: Chapter 10"

## Output

EPUB files are saved to the `output/` directory by default.
