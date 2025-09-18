import pytest
from unittest.mock import Mock, patch
from src.bot import handle_instagram_url, handle_start, handle_help
from telegram import Update
from telegram.ext import ContextTypes

@pytest.fixture
def mock_update():
    update = Mock(spec=Update)
    update.message = Mock()
    update.message.chat_id = 123456789
    update.message.chat.type = "private"
    return update

@pytest.fixture
def mock_context():
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    return context

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    """Test the /start command handler"""
    await handle_start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args[0][0]
    assert "Welcome" in call_args

@pytest.mark.asyncio
async def test_help_command(mock_update, mock_context):
    """Test the /help command handler"""
    await handle_help(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args[0][0]
    assert "commands" in call_args.lower()

@pytest.mark.asyncio
async def test_instagram_url_handler_success(mock_update, mock_context):
    """Test successful Instagram URL handling"""
    mock_update.message.text = "https://www.instagram.com/p/ABC123/"
    
    with patch('src.bot.instagram_downloader') as mock_downloader:
        # Mock successful download
        mock_downloader.download.return_value.success = True
        mock_downloader.download.return_value.file_paths = ["/path/to/downloaded/file.jpg"]
        
        await handle_instagram_url(mock_update, mock_context)
        
        # Verify progress messages
        assert mock_update.message.reply_text.call_count >= 2
        # Verify download was attempted
        mock_downloader.download.assert_called_once_with(mock_update.message.text)

@pytest.mark.asyncio
async def test_instagram_url_handler_failure(mock_update, mock_context):
    """Test Instagram URL handling with download failure"""
    mock_update.message.text = "https://www.instagram.com/p/ABC123/"
    
    with patch('src.bot.instagram_downloader') as mock_downloader:
        # Mock failed download
        mock_downloader.download.return_value.success = False
        mock_downloader.download.return_value.error = "Download failed"
        
        await handle_instagram_url(mock_update, mock_context)
        
        # Verify error message was sent
        error_message = mock_update.message.reply_text.call_args_list[-1][0][0]
        assert "failed" in error_message.lower()

@pytest.mark.asyncio
async def test_instagram_url_handler_invalid_url(mock_update, mock_context):
    """Test handling of invalid Instagram URL"""
    mock_update.message.text = "https://not-instagram.com/something"
    
    await handle_instagram_url(mock_update, mock_context)
    
    # Verify error message for invalid URL
    error_message = mock_update.message.reply_text.call_args[0][0]
    assert "valid Instagram URL" in error_message.lower()

@pytest.mark.asyncio
async def test_instagram_url_handler_rate_limit(mock_update, mock_context):
    """Test handling of rate limit during download"""
    mock_update.message.text = "https://www.instagram.com/p/ABC123/"
    
    with patch('src.bot.instagram_downloader') as mock_downloader:
        # Mock rate limit error
        mock_downloader.download.return_value.success = False
        mock_downloader.download.return_value.error = "Rate limit exceeded"
        
        await handle_instagram_url(mock_update, mock_context)
        
        # Verify rate limit message
        rate_limit_message = mock_update.message.reply_text.call_args_list[-1][0][0]
        assert "rate limit" in rate_limit_message.lower()