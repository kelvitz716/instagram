"""Tests for Instagram content downloading functionality."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.services.instagram_downloader import InstagramDownloader
from src.core.config import InstagramConfig

# Mark all tests in this module as asyncio tests
pytestmark = pytest.mark.asyncio

@pytest.fixture
def downloads_path(tmp_path):
    """Create a temporary downloads directory."""
    return tmp_path / "downloads"

@pytest.fixture
def instagram_config():
    """Create a test configuration."""
    config = InstagramConfig()
    config.download_timeout = 5  # Short timeout for tests
    config.username = "test_user"  # Test username
    return config

@pytest.fixture
def downloader(downloads_path, instagram_config):
    """Create an InstagramDownloader instance."""
    return InstagramDownloader(instagram_config, downloads_path)

@pytest.mark.parametrize("url,expected_files", [
    ("https://www.instagram.com/p/test123/", ["test_image.jpg"]),
    ("https://www.instagram.com/reel/test456/", ["test_video.mp4"]),
])
async def test_download_post(downloader, downloads_path, url, expected_files):
    """Test downloading various types of Instagram posts."""
    # Mock the actual download function
    with patch.object(downloader, '_download_post') as mock_download:
        mock_files = [downloads_path / f for f in expected_files]
        mock_download.return_value = mock_files
        
        # Perform the download
        files = await downloader.download_post(url)
        
        # Verify results
        assert files == mock_files
        mock_download.assert_called_once_with(url)

async def test_download_stories(downloader, downloads_path):
    """Test downloading Instagram stories."""
    username = "test_user"
    expected_files = [
        downloads_path / "story_1.jpg",
        downloads_path / "story_2.mp4"
    ]
    
    # Mock the story download function
    with patch.object(downloader, '_download_stories') as mock_download:
        mock_download.return_value = expected_files
        
        # Perform the download
        files = await downloader.download_stories(username)
        
        # Verify results
        assert files == expected_files
        mock_download.assert_called_once_with(username)

async def test_download_error_handling(downloader):
    """Test error handling during downloads."""
    with patch.object(downloader, '_download_post', side_effect=Exception("Network error")):
        with pytest.raises(Exception, match="Network error"):
            await downloader.download_post("https://www.instagram.com/p/invalid/")
