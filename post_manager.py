#!/usr/bin/env python3
"""
CLI interface for managing Patreon post subscriptions and viewing posts.
"""

import sys
import json
import click
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

from config import Config
from post_storage import PostStorage
from post_fetcher import PostFetcher
from sync_service import SyncService


@click.group()
@click.option('--settings', default='./settings.json', help='Path to settings file')
@click.pass_context
def cli(ctx, settings):
    """Patreon Post Manager - Download and manage Patreon posts."""
    ctx.ensure_object(dict)
    ctx.obj['settings'] = settings


@cli.command()
@click.argument('url')
@click.option('--name', help='Display name for the creator')
@click.pass_context
def add(ctx, url, name):
    """Add a creator to follow.
    
    URL should be the Patreon creator's posts page, e.g.:
    https://www.patreon.com/c/example-creator/posts
    """
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    fetcher.add_creator(url, name)


@cli.command()
@click.argument('creator')
@click.pass_context
def remove(ctx, creator):
    """Remove a creator from the follow list."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    fetcher.remove_creator(creator)


@cli.command('list')
@click.pass_context
def list_creators(ctx):
    """List all followed creators."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    creators = fetcher.list_creators()
    
    if not creators:
        click.echo("No creators added yet. Use 'add' command to add creators.")
        return
    
    click.echo("\nFollowed Creators:")
    click.echo("-" * 60)
    
    for c in creators:
        status = "✓" if c['enabled'] else "○"
        click.echo(f"{status} {c['name']} ({c['slug']})")
        click.echo(f"   Posts: {c['post_count']}")
        if c['latest_post']:
            click.echo(f"   Latest: {c['latest_post'][:10]}")
        click.echo()


@cli.command()
@click.option('--full', is_flag=True, help='Do a full sync (download all posts)')
@click.option('--creator', help='Sync only a specific creator')
@click.option('--no-headless', is_flag=True, help='Show browser window')
@click.pass_context
def sync(ctx, full, creator, no_headless):
    """Sync posts from Patreon."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    
    try:
        Config.validate()
        
        if not fetcher.authenticate(headless=not no_headless):
            click.echo("✗ Authentication failed")
            sys.exit(1)
        
        if creator:
            # Find creator URL
            creators = fetcher.list_creators()
            creator_info = next(
                (c for c in creators if c['slug'] == creator or c['name'].lower() == creator.lower()),
                None
            )
            
            if not creator_info:
                click.echo(f"✗ Creator '{creator}' not found")
                sys.exit(1)
            
            if full:
                fetcher.fetch_all_posts(creator_info['url'])
            else:
                fetcher.fetch_recent_posts(creator_info['url'])
        else:
            results = fetcher.sync_all_creators(full_sync=full)
            
            click.echo("\nSync Results:")
            click.echo("-" * 40)
            total = sum(results.values())
            for slug, count in results.items():
                click.echo(f"  {slug}: {count} new posts")
            click.echo(f"\nTotal: {total} new posts")
    
    finally:
        fetcher.close()


@cli.command()
@click.pass_context
def service(ctx):
    """Start the background sync service."""
    from sync_service import run_service
    run_service()


@cli.command()
@click.argument('creator')
@click.option('--limit', default=20, help='Number of posts to show')
@click.option('--offset', default=0, help='Offset for pagination')
@click.option('--search', help='Search posts by title')
@click.pass_context
def posts(ctx, creator, limit, search, offset):
    """List posts from a creator."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    
    if search:
        posts = fetcher.storage.search_posts(search, creator)
        click.echo(f"\nSearch results for '{search}' in {creator}:")
    else:
        posts = fetcher.storage.get_posts_by_creator(creator, limit=limit, offset=offset)
        click.echo(f"\nPosts from {creator} ({offset+1}-{offset+len(posts)}):")
    
    click.echo("-" * 60)
    
    if not posts:
        click.echo("No posts found.")
        return
    
    for i, post in enumerate(posts, start=offset+1):
        date = post.published_date[:10] if post.published_date else "N/A"
        click.echo(f"{i:3}. [{date}] {post.title}")
        click.echo(f"     ID: {post.id}")


@cli.command()
@click.argument('creator')
@click.argument('post_id')
@click.option('--html', is_flag=True, help='Show raw HTML content')
@click.option('--save', type=click.Path(), help='Save content to file')
@click.pass_context
def view(ctx, creator, post_id, html, save):
    """View a specific post."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    post = fetcher.storage.get_post(post_id, creator)
    
    if not post:
        click.echo(f"Post '{post_id}' not found for creator '{creator}'")
        sys.exit(1)
    
    click.echo("\n" + "=" * 60)
    click.echo(f"Title: {post.title}")
    click.echo(f"Date: {post.published_date}")
    click.echo(f"URL: {post.url}")
    click.echo("=" * 60 + "\n")
    
    if html:
        content = post.content
    else:
        # Convert HTML to plain text
        soup = BeautifulSoup(post.content, 'html.parser')
        content = soup.get_text(separator='\n\n')
    
    if save:
        with open(save, 'w') as f:
            f.write(content)
        click.echo(f"✓ Saved to {save}")
    else:
        click.echo(content)
    
    if post.images:
        click.echo("\n" + "-" * 40)
        click.echo(f"Images ({len(post.images)}):")
        for img in post.images:
            click.echo(f"  - {img}")


@cli.command()
@click.argument('creator')
@click.argument('query')
@click.pass_context  
def search(ctx, creator, query):
    """Search posts by title or content."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    posts = fetcher.storage.search_posts(query, creator)
    
    click.echo(f"\nSearch results for '{query}':")
    click.echo("-" * 60)
    
    if not posts:
        click.echo("No posts found.")
        return
    
    for i, post in enumerate(posts, 1):
        date = post.published_date[:10] if post.published_date else "N/A"
        click.echo(f"{i:3}. [{date}] {post.title}")
        click.echo(f"     ID: {post.id}")


@cli.command()
@click.argument('creator')
@click.pass_context
def history(ctx, creator):
    """Show sync history for a creator."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    history = fetcher.storage.get_sync_history(creator)
    
    click.echo(f"\nSync History for {creator}:")
    click.echo("-" * 60)
    
    if not history:
        click.echo("No sync history.")
        return
    
    for entry in history:
        time = entry['sync_time'][:19].replace('T', ' ')
        status = "✓" if entry['status'] == 'success' else "✗"
        click.echo(f"{status} {time} - {entry['posts_added']} new posts")
        if entry['error_message']:
            click.echo(f"   Error: {entry['error_message']}")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current status and statistics."""
    fetcher = PostFetcher(settings_path=ctx.obj['settings'])
    creators = fetcher.list_creators()
    
    total_posts = sum(c['post_count'] for c in creators)
    
    click.echo("\n" + "=" * 60)
    click.echo("Patreon Post Manager Status")
    click.echo("=" * 60)
    
    click.echo(f"\nCreators: {len(creators)}")
    click.echo(f"Total Posts: {total_posts}")
    
    if fetcher.settings.get('sync', {}).get('interval_hours'):
        click.echo(f"Sync Interval: {fetcher.settings['sync']['interval_hours']} hours")
    
    click.echo(f"\nDatabase: {fetcher.settings['storage']['database']}")
    
    if creators:
        click.echo("\nPer-Creator Stats:")
        click.echo("-" * 40)
        for c in creators:
            click.echo(f"  {c['name']}: {c['post_count']} posts")


@cli.command()
@click.argument('hours', type=float)
@click.pass_context
def interval(ctx, hours):
    """Set sync interval in hours."""
    settings_path = Path(ctx.obj['settings'])
    
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        settings['sync']['interval_hours'] = hours
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=4)
        click.echo(f"✓ Sync interval set to {hours} hours")
    else:
        click.echo("Settings file not found.")


if __name__ == '__main__':
    cli()
