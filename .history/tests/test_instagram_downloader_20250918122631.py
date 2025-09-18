from typing import Dict, Any
import pytest
from unittest.mock import Mock, patch, ANY
import os
from pathlib import Path
from datetime import datetime

from src.services.instagram_downloader import InstagramDownloader
from src.core.config import Config
from src.core.session_manager import InstagramSessionManager

# Test constants
TEST_POST_URL = "https://www.instagram.com/p/ABC123/"
TEST_REEL_URL = "https://www.instagram.com/reels/DEF456/"
TEST_STORY_URL = "https://www.instagram.com/stories/username/789012/"
TEST_DOWNLOAD_PATH = Path("downloads/2025-09-18_12-00-00/image.jpg")

class TestConfig:
    """Test configuration class that mimics the real Config class"""
    def __init__(self, downloads_path: Path):
        self.DOWNLOADS_PATH = downloads_path
        self.INSTAGRAM_USERNAME = "test_user"
        self.INSTAGRAM_PASSWORD = "test_pass"
        self.COOKIES_PATH = Path("/tmp/cookies.txt")
        self.DOWNLOAD_TIMEOUT = 30

@pytest.fixture
def downloads_path(tmp_path) -> Path:
    """Create a temporary directory for downloads
    
    Returns:
        Path: Temporary directory path for test downloads
    """
    downloads = tmp_path / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads

@pytest.fixture
def config(downloads_path) -> TestConfig:
    """Create a test configuration
    
    Args:
        downloads_path: Pytest fixture providing temporary downloads directory
    
    Returns:
        TestConfig: Configuration object for testing
    """
    return TestConfig(downloads_path)

@pytest.fixture
def downloader(config: TestConfig, mock_session_manager) -> InstagramDownloader:
    """Create an InstagramDownloader instance for testing
    
    Args:
        config: Test configuration fixture
        mock_session_manager: Mocked session manager fixture
    
    Returns:
        InstagramDownloader: Configured downloader instance
    """
    return InstagramDownloader(config=config)

@pytest.fixture
def mock_session_manager():
    with patch('src.services.instagram_downloader.InstagramSessionManager') as mock:
        instance = mock.return_value
        instance.get_cookies.return_value = {'sessionid': 'test_session'}
        yield instance

def test_extract_identifier_from_post_url(downloader):
    """Test URL identifier extraction for different Instagram URLs"""
    # Test post URL
    url = "https://www.instagram.com/p/ABC123/"
    identifier = downloader._extract_identifier(url)
    assert identifier == "ABC123"
    
    # Test reel URL
    url = "https://www.instagram.com/reels/DEF456/"
    identifier = downloader._extract_identifier(url)
    assert identifier == "DEF456"
    
    # Test story URL
    url = "https://www.instagram.com/stories/username/789012/"
    identifier = downloader._extract_identifier(url)
    assert identifier == "789012"

def test_extract_identifier_invalid_url(downloader):
    """Test URL identifier extraction with invalid URL"""
    url = "https://instagram.com/invalid/url"
    with pytest.raises(ValueError):
        downloader._extract_identifier(url)

def test_get_download_path(downloader):
    """Test download path generation"""
    expected_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = downloader._get_download_path()
    assert expected_date in path
    assert path.startswith(os.path.join(os.getcwd(), "downloads"))

@pytest.mark.asyncio
async def test_download_content_success(downloader, mock_session_manager):
    """Test successful content download"""
    url = "https://www.instagram.com/p/ABC123/"
    
    # Mock subprocess.run for gallery-dl
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout=b"downloads/2025-09-18_12-00-00/image.jpg\n",
            stderr=b""
        )
        
        result = await downloader.download(url)
        assert result.success is True
        assert len(result.file_paths) == 1
        assert "image.jpg" in result.file_paths[0]
        
        # Verify gallery-dl was called with correct arguments
        mock_run.assert_called_once_with(
            [ANY, '--cookies-from-browser', 'firefox', '--write-metadata', '--verbose', '-D', ANY, url],
            capture_output=True,
            text=True
        )

@pytest.mark.asyncio
async def test_download_content_failure(downloader, mock_session_manager):
    """Test content download failure"""
    url = "https://www.instagram.com/p/ABC123/"
    
    # Mock subprocess.run for gallery-dl failure
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=1,
            stdout=b"",
            stderr=b"Error: Failed to download"
        )
        
        result = await downloader.download(url)
        assert result.success is False
        assert "Failed to download" in result.error

@pytest.mark.asyncio
async def test_download_rate_limited(downloader, mock_session_manager):
    """Test download with rate limiting"""
    url = "https://www.instagram.com/p/ABC123/"
    
    # Mock subprocess.run for rate limit response
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=1,
            stdout=b"",
            stderr=b"429 Too Many Requests"
        )
        
        result = await downloader.download(url)
        assert result.success is False
        assert "rate limit" in result.error.lower()

def test_is_instagram_url(downloader):
    """Test Instagram URL validation"""
    assert downloader._is_instagram_url("https://www.instagram.com/p/ABC123/") is True
    assert downloader._is_instagram_url("https://www.instagram.com/reels/DEF456/") is True
    assert downloader._is_instagram_url("https://www.instagram.com/stories/user/789012/") is True
    assert downloader._is_instagram_url("https://example.com/not/instagram") is False