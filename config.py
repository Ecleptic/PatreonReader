"""Configuration management for Patreon to EPUB converter."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration."""
    
    # Authentication
    PATREON_EMAIL = os.getenv('PATREON_EMAIL')
    PATREON_PASSWORD = os.getenv('PATREON_PASSWORD')
    PATREON_SESSION = os.getenv('PATREON_SESSION')  # Manual session cookie for bypassing login
    
    # Directories
    OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', './output'))
    CACHE_DIR = Path(os.getenv('CACHE_DIR', './cache'))
    
    # Patreon API/URLs
    PATREON_LOGIN_URL = 'https://www.patreon.com/api/login'
    PATREON_BASE_URL = 'https://www.patreon.com'
    
    # User agent for requests
    USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.PATREON_EMAIL or not cls.PATREON_PASSWORD:
            raise ValueError(
                "PATREON_EMAIL and PATREON_PASSWORD must be set in .env file"
            )
        
        # Create directories if they don't exist
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)
