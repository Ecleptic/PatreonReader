# Patreon Reader

A self-hosted web application to read and manage your Patreon posts offline. Features a mobile-friendly PWA with offline support, automatic background syncing, and read/unread tracking.

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## ⚠️ Disclaimer

**This application is NOT a tool for piracy or illegally downloading content.**

Patreon Reader is an alternative viewer for reading text content that you already have legitimate access to through your Patreon subscriptions. It provides a better reading experience with offline support, but requires you to be an active subscriber to access the content.

I do not condone or promote piracy in any form. Please support the creators you enjoy by maintaining active subscriptions.

## Features

- 📱 **Progressive Web App (PWA)** - Install on your phone, works offline
- 🔄 **Background Sync** - Automatically fetches new posts every 2 hours
- 📖 **Reader Mode** - Clean, distraction-free reading experience
- 🌙 **Dark/Light Theme** - System theme support
- ✅ **Read Tracking** - Mark posts as read/unread
- 📴 **Offline Support** - Save posts for offline reading
- 🔐 **API Authentication** - Secure with Bearer token
- 🐳 **Docker Ready** - Easy deployment

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/patreon-reader.git
cd patreon-reader

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# Start with Docker Compose
docker compose up -d

# Open http://localhost:8000
```

### Option 2: Local Development

```bash
# Clone and install
git clone https://github.com/yourusername/patreon-reader.git
cd patreon-reader
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Start the server
python -m uvicorn api_server:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_TOKEN` | Bearer token for API auth (empty = disabled) | - |
| `PATREON_EMAIL` | Patreon login email | - |
| `PATREON_PASSWORD` | Patreon login password | - |
| `SYNC_INTERVAL_HOURS` | Background sync interval | `2` |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `PORT` | Server port | `8000` |
| `TZ` | Timezone | `UTC` |

### Generating an API Token

```bash
# Generate a secure random token
openssl rand -hex 32
```

Add the token to your `.env` file and use it in API requests:
```
Authorization: Bearer your-token-here
```

## Usage

### Web Interface

1. Open http://localhost:8000 in your browser
2. Click the ⚙️ settings icon
3. Add a Patreon creator URL (e.g., `https://www.patreon.com/c/example-creator/posts`)
4. Posts will automatically sync

### Installing as PWA (Android)

1. Open the app in Chrome on your Android device
2. Tap the menu (⋮) → "Add to Home Screen"
3. The app will install and work offline

### Offline Reading

1. Open a post you want to save
2. Click the ⬇️ button in the navigation bar
3. The post is now saved for offline reading
4. View saved posts in Settings → Offline Storage

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/creators` | GET | List all creators |
| `/api/creators` | POST | Add a creator |
| `/api/creators/{id}` | DELETE | Remove a creator |
| `/api/posts/{creator_id}` | GET | Get posts for creator |
| `/api/posts/{creator_id}/{post_id}` | GET | Get single post |
| `/api/posts/{creator_id}/{post_id}/read` | POST | Mark as read |
| `/api/posts/{creator_id}/{post_id}/unread` | POST | Mark as unread |
| `/api/sync` | POST | Trigger manual sync |
| `/api/sync/status` | GET | Get sync status |

## Docker Deployment

### Docker Compose

```yaml
services:
  patreon-reader:
    image: patreon-reader:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - API_TOKEN=${API_TOKEN}
      - PATREON_EMAIL=${PATREON_EMAIL}
      - PATREON_PASSWORD=${PATREON_PASSWORD}
    volumes:
      - patreon_data:/app/data

volumes:
  patreon_data:
```

### Building the Image

```bash
docker build -t patreon-reader .
```

## Project Structure

```
patreon-reader/
├── api_server.py       # FastAPI server
├── storage.py          # SQLite database layer
├── post_fetcher.py     # Patreon scraping
├── sync_service.py     # Background sync
├── static/
│   ├── index.html      # Web interface
│   ├── styles.css      # Styling
│   ├── app.js          # Frontend logic
│   ├── sw.js           # Service Worker
│   ├── manifest.json   # PWA manifest
│   └── icons/          # App icons
├── scripts/
│   └── build-apk.sh    # Android APK build script
├── twa-manifest.json   # TWA config for Android
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Android APK Build

You can build an Android APK that wraps the PWA using [Bubblewrap](https://github.com/nicholascruz/nicholascruz).

### Via GitHub Actions

1. **Manual trigger**: Go to Actions → "Build Android APK" → Run workflow
   - Enter your server hostname (e.g., `myserver.com`)
   - Enter version (e.g., `1.0.0`)

2. **PR comment trigger**: Comment on any PR with:
   ```
   /build-apk host=myserver.com version=1.0.0
   ```

### Local Build

```bash
# Install prerequisites
npm install -g @bubblewrap/cli

# Build APK (requires your server to be running at the host)
./scripts/build-apk.sh your-server.com 1.0.0
```

**Note:** The APK build requires your PWA to be accessible at the specified host URL so the manifest can be validated.

## EPUB Converter (Legacy)

The original EPUB converter functionality is still available:

```bash
# Download and convert to EPUB
python main.py https://www.patreon.com/c/creator/posts

# Update existing EPUB with new chapters
python main.py https://www.patreon.com/c/creator/posts --update
```

## Security Notes

⚠️ **Before publishing to GitHub:**

1. Never commit `.env` files with credentials
2. Add `.env` to `.gitignore`
3. Use `.env.example` as a template
4. Generate a strong `API_TOKEN` for production
5. Consider running behind a reverse proxy (nginx/Caddy) with HTTPS

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please open an issue or PR.
