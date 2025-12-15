"""Background sync service for periodically fetching new Patreon posts."""

import time
import signal
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable
import json
from pathlib import Path

from post_fetcher import PostFetcher
from post_storage import PostStorage


class SyncService:
    """Background service for periodically syncing Patreon posts."""
    
    def __init__(self, settings_path: str = "./settings.json"):
        self.settings_path = Path(settings_path)
        self.fetcher = PostFetcher(settings_path=settings_path)
        self.storage = self.fetcher.storage
        self.running = False
        self._stop_event = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None
        self._on_new_posts: Optional[Callable] = None
        
        # Load sync settings
        self._load_sync_settings()
    
    def _load_sync_settings(self):
        """Load sync interval from settings."""
        if self.settings_path.exists():
            with open(self.settings_path, 'r') as f:
                settings = json.load(f)
            self.interval_hours = settings.get('sync', {}).get('interval_hours', 2)
        else:
            self.interval_hours = 2
    
    def set_interval(self, hours: float):
        """Set sync interval in hours."""
        self.interval_hours = hours
        
        # Update settings file
        if self.settings_path.exists():
            with open(self.settings_path, 'r') as f:
                settings = json.load(f)
            settings['sync']['interval_hours'] = hours
            with open(self.settings_path, 'w') as f:
                json.dump(settings, f, indent=4)
    
    def set_callback(self, callback: Callable):
        """Set callback function to be called when new posts are found."""
        self._on_new_posts = callback
    
    def initial_sync(self) -> dict:
        """
        Perform initial full sync for all creators.
        This downloads ALL posts for each creator.
        """
        print("=" * 60)
        print("Initial Full Sync")
        print("=" * 60)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if not self.fetcher.authenticate(headless=True):
            print("✗ Failed to authenticate")
            return {}
        
        results = self.fetcher.sync_all_creators(full_sync=True)
        
        print("\n" + "=" * 60)
        print("Initial Sync Complete")
        print("=" * 60)
        
        total = sum(results.values())
        print(f"Total new posts: {total}")
        
        for slug, count in results.items():
            print(f"  - {slug}: {count} posts")
        
        return results
    
    def quick_sync(self) -> dict:
        """
        Perform a quick sync checking only recent posts.
        """
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Quick sync started...")
        
        if not self.fetcher.auth:
            if not self.fetcher.authenticate(headless=True):
                print("✗ Failed to authenticate")
                return {}
        
        results = self.fetcher.sync_all_creators(full_sync=False)
        
        total = sum(results.values())
        if total > 0:
            print(f"✓ Found {total} new posts")
            
            if self._on_new_posts:
                self._on_new_posts(results)
        else:
            print("✓ No new posts")
        
        return results
    
    def _sync_loop(self):
        """Main sync loop running in background thread."""
        interval_seconds = self.interval_hours * 3600
        
        while not self._stop_event.is_set():
            try:
                self.quick_sync()
            except Exception as e:
                print(f"✗ Sync error: {e}")
            
            # Wait for next sync interval (check stop event periodically)
            wait_time = 0
            while wait_time < interval_seconds and not self._stop_event.is_set():
                time.sleep(min(60, interval_seconds - wait_time))
                wait_time += 60
        
        print("Sync loop stopped.")
    
    def start_background_sync(self):
        """Start the background sync service."""
        if self.running:
            print("Sync service is already running.")
            return
        
        print(f"Starting background sync service (interval: {self.interval_hours}h)...")
        
        self.running = True
        self._stop_event.clear()
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        
        print(f"✓ Background sync started. Next sync in {self.interval_hours} hours.")
    
    def stop_background_sync(self):
        """Stop the background sync service."""
        if not self.running:
            return
        
        print("Stopping background sync...")
        self._stop_event.set()
        
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        
        self.running = False
        print("✓ Background sync stopped.")
    
    def get_status(self) -> dict:
        """Get current service status."""
        creators = self.fetcher.list_creators()
        
        status = {
            'running': self.running,
            'interval_hours': self.interval_hours,
            'creators': creators,
            'total_posts': sum(c['post_count'] for c in creators)
        }
        
        return status
    
    def close(self):
        """Clean up resources."""
        self.stop_background_sync()
        self.fetcher.close()


def run_service():
    """Run the sync service as a standalone process."""
    service = SyncService()
    
    def signal_handler(signum, frame):
        print("\nReceived shutdown signal...")
        service.close()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("Patreon Post Sync Service")
    print("=" * 60)
    
    # Show current creators
    creators = service.fetcher.list_creators()
    if not creators:
        print("\n⚠ No creators configured. Add creators to settings.json first.")
        print("Example:")
        print('  {"creators": [{"name": "Creator Name", "url": "https://www.patreon.com/c/creator/posts"}]}')
        return
    
    print(f"\nTracking {len(creators)} creator(s):")
    for c in creators:
        print(f"  - {c['name']}: {c['post_count']} posts")
    
    # Perform initial sync if needed
    has_posts = any(c['post_count'] > 0 for c in creators)
    
    if not has_posts:
        print("\n" + "-" * 40)
        print("No posts in database. Performing initial sync...")
        service.initial_sync()
    else:
        print("\n" + "-" * 40)
        print("Performing quick sync...")
        service.quick_sync()
    
    # Start background sync
    service.start_background_sync()
    
    print("\n" + "=" * 60)
    print("Service running. Press Ctrl+C to stop.")
    print("=" * 60)
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        service.close()


if __name__ == "__main__":
    run_service()
