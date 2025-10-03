# Instagram Content Downloader Bot

A sophisticated Telegram bot for downloading Instagram content, supporting posts, reels, stories, highlights, and profiles with optimized performance and resilient service-based architecture.

## 🚀 Features

- Download Instagram posts (single image/video)
- Download Instagram reels
- Download Instagram carousels (multiple images/videos)
- Upload files to Telegram with progress tracking
- SQLite database for operation logging
- Browser cookie authentication (Firefox)
- Automatic file type detection
- Configurable upload methods (Bot API or Telethon)
- Smart retry mechanism with exponential backoff
- Progress tracking for downloads and uploads
- Comprehensive error handling
- Rate limiting and flood control
- Configurable file watching
- Enhanced session management
- Docker support with health checks
- Easy deployment scripts

Note: Stories and highlights are not supported as they require Instagram's private API access.

## Requirements

- Python 3.10 or higher
- Firefox browser (for Instagram authentication)
- Access to Telegram API (bot token, API ID, and API hash)

## Quick Start with Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/kelvitz716/instagram.git
cd instagram
```

2. Set up your configuration:
```bash
# Copy example environment file
cp example.env .env

# Edit .env with your settings
nano .env  # or use any text editor
```

3. Add your Instagram cookies:
- Create or copy your `gallery-dl-cookies.txt` file into the project directory

4. Run the initial setup script:
```bash
chmod +x setup.sh
./setup.sh
```

During the first run, the setup script will:
1. Create necessary directories and set permissions
2. Run database migrations
3. Guide you through Telegram authentication
4. Save your Telegram session for future use
5. Start the bot in detached mode

After initial setup, use these commands for daily operation:

### Docker Commands

- Start bot:  `docker compose up -d`
- Stop bot:   `docker compose down`
- View logs:  `docker compose logs -f`
- Restart:    `docker compose restart`
- Status:     `docker compose ps`

### Important Notes

- The Telegram session is saved in the `sessions` directory
- DO NOT delete the `sessions` folder or its contents
- The session persists across bot restarts and updates
- To re-run setup, delete the `.setup_complete` file and run `setup.sh` again

### Docker Volumes

The bot uses Docker volumes to persist data:
- `./downloads`: Stores downloaded media files
- `gallery-dl-cookies.txt`: Instagram authentication cookies
- `.env`: Configuration file

## Manual Installation (Alternative)

If you prefer to run without Docker, follow these steps:

1. Clone the repository:
```bash
git clone https://github.com/kelvitz716/instagram.git
cd instagram
```

2. Create a virtual environment and activate it:
```bash
python -m venv myenv
source myenv/bin/activate  # Linux/macOS
# or
myenv\Scripts\activate  # Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy and configure environment variables:
```bash
cp example.env .env
# Edit .env with your settings
```

Required settings:
```env
BOT_TOKEN=your_telegram_bot_token
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
TARGET_CHAT_ID=your_target_chat_id
```

Optional settings (see example.env for all options):
```env
INSTAGRAM_USERNAME=your_instagram_username
FIREFOX_COOKIES_PATH=custom/path/to/cookies.sqlite
MAX_CONCURRENT_UPLOADS=3
BATCH_SIZE=10
FILE_WATCHER_ENABLED=true
```

5. Log in to Instagram in Firefox:
- Open Firefox
- Go to instagram.com
- Log in to your account
- Make sure to check "Remember me"

## Usage

1. Start the bot:
```bash
python bot.py
```

2. In Telegram, send commands to the bot:
- `/instagram <url>` - Download Instagram post, carousel, or reel
- `/login [username]` - Log in with Firefox cookies
- `/stats` - Show detailed statistics
- `/debug_firefox` - Debug Firefox cookie detection

Note: Simply paste the URL of any Instagram post, carousel, or reel to download it.

## Enhanced Features

### Smart Upload Selection
- Automatically chooses between Bot API and Telethon based on file size
- Fallback mechanism for failed uploads
- Configurable size thresholds

### Progress Tracking
- Download progress with percentage and file size
- Upload progress for large files
- Batch processing status updates
- Rate-limited status messages

### Error Handling
- Exponential backoff for retries
- Network error recovery
- Flood control protection
- Session management and renewal

### File Management
- Automatic file type detection
- Support for various media formats
- Temporary file cleanup
- Organized directory structure

### Performance
- Concurrent upload handling
- Rate limiting protection
- Memory usage optimization
- Connection pooling

## Docker Health Checks

The Docker container includes health checks that:
- Verify the bot's connection to Telegram
- Monitor the bot's operational status
- Automatically restart if issues are detected

Health check status can be viewed with:
```bash
docker inspect instagram-telegram-bot --format='{{.State.Health.Status}}'
```

## Architecture

The bot follows a service-based architecture:

```
instagram-bot/
├── src/                 # Source code
├── tests/              # Test files
├── Dockerfile          # Docker configuration
├── docker-compose.yml  # Docker Compose configuration
├── setup.sh           # Setup script
├── healthcheck.py     # Container health check
├── bot.py             # Entry point
└── requirements.txt   # Dependencies
```

## Configuration

See `example.env` for all available configuration options, including:
- Telegram settings
- Instagram options
- Upload configurations
- Database settings
- File watcher options
- Logging preferences
- Performance tuning

## Troubleshooting

### Docker Issues

1. Container won't start:
   - Check logs: `docker-compose logs`
   - Verify .env configuration
   - Ensure gallery-dl-cookies.txt exists

2. Health check failing:
   - Verify bot token is correct
   - Check Telegram API accessibility
   - Review logs for specific errors

3. Permission issues:
   - Ensure proper ownership of mounted volumes
   - Check file permissions in host directory

### Common Problems

1. Instagram authentication:
   - Verify cookie file is properly formatted
   - Check cookie file permissions
   - Ensure cookies are not expired

2. Network issues:
   - Check container networking
   - Verify proxy settings if used
   - Ensure required ports are accessible

## License

This project is licensed under the MIT License - see the LICENSE file for details.
