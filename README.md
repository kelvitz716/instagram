# Instagram Downloader Bot

A Telegram bot that downloads content from Instagram posts, reels, and carousels using gallery-dl with Firefox cookies.

## Features

- Download Instagram posts (single image/video)
- Download Instagram reels
- Download Instagram carousels (multiple images/videos)
- Upload files to Telegram with progress tracking
- SQLite database for operation logging
- Browser cookie authentication (Firefox)
- Automatic file type detection
- Configurable upload methods (Bot API or Telethon)
- Retry mechanism with exponential backoff

Note: Stories and highlights are not supported as they require Instagram's private API access.

## Requirements

- Python 3.10 or higher
- Firefox browser (for Instagram authentication)
- Access to Telegram API (bot token, API ID, and API hash)

## Installation

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

4. Set up environment variables in `.env`:
```env
BOT_TOKEN=your_telegram_bot_token
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
TARGET_CHAT_ID=your_target_chat_id
INSTAGRAM_USERNAME=your_instagram_username
```

5. Log in to Instagram in Firefox:
- Open Firefox
- Go to instagram.com
- Log in to your account
- Make sure to check "Remember me"

## Usage

1. Start the bot:
```bash
python run_bot.py
```

2. In Telegram, send commands to the bot:
- `/instagram <url>` - Download Instagram post, carousel, or reel
- `/stats` - Show bot statistics

Note: Simply paste the URL of any Instagram post, carousel, or reel to download it.

## Important Notes

Stories and highlights are not supported by this bot as they require Instagram's private API access. The bot uses Firefox cookies for authentication, which only provides access to content that's available through the web interface.

## Architecture

- Service-based architecture for maintainability
- Retry mechanism for handling transient failures
- Progress tracking for long-running operations
- SQLite database for persistent storage
- Support for both Bot API and Telethon uploaders
- Firefox cookie-based authentication for Instagram

## Configuration

The bot can be configured through environment variables or a `.env` file. See the sample `.env` file for available options.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
