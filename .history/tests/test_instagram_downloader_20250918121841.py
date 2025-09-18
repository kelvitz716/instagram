import pytest
from unittest.mock import Mock, patch
import os
from pathlib import Path
from src.services.instagram_downloader import InstagramDownloader
from datetime import datetimet pytest
from unittest.mock import Mock, patch, ANY
import os
from src.services.instagram_downloader import InstagramDownloader
from datetime import datetime

@pytest.fixture
def config():
    """Create a mock configuration"""
    config = Mock()
    config.DOWNLOADS_PATH = "/tmp/downloads"
    return config

@pytest.fixture
def downloads_path(tmp_path):
    """Create a temporary directory for downloads"""
    return str(tmp_path / "downloads")

@pytest.fixture
def downloader(config, downloads_path):
    return InstagramDownloader(config=config, downloads_path=Path(downloads_path))

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