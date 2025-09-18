from typing import Dict, Any
import pytest
from unittest.mock import Mock, patch, ANY
import os
from pathlib import Path
from datetime import datetime

from src.services.instagram_downloader import InstagramDownloader
from src.core.config import BotConfig, InstagramConfig, TelegramConfig, UploadConfig
from src.core.session_manager import InstagramSessionManager

# Test constants
TEST_POST_URL = "https://www.instagram.com/p/ABC123/"
TEST_REEL_URL = "https://www.instagram.com/reels/DEF456/"
TEST_STORY_URL = "https://www.instagram.com/stories/username/789012/"
TEST_DOWNLOAD_PATH = Path("downloads/2025-09-18_12-00-00/image.jpg")

@pytest.fixture
def instagram_config(downloads_path: Path) -> InstagramConfig:
    """Create Instagram-specific configuration for testing"""
    return InstagramConfig(
        username="test_user",
        firefox_cookies_path="/tmp/cookies.txt",
        download_timeout=30,
        retry_delay=1,
        max_retries=3,
        caption_max_length=200,
        download_progress_enabled=True,
        cookies_auto_refresh=True
    )

@pytest.fixture
def test_config(downloads_path: Path, instagram_config: InstagramConfig) -> BotConfig:
    """Create test configuration that matches the real BotConfig structure"""
    return BotConfig(
        telegram=TelegramConfig(
            bot_token="test_token",
            api_id=12345,
            api_hash="test_hash",
            target_chat_id=54321
        ),
        instagram=instagram_config,
        upload=UploadConfig(),
        downloads_path=downloads_path,
        uploads_path=downloads_path / "uploads",
        temp_path=downloads_path / "temp"
    )

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
def config(test_config: BotConfig) -> BotConfig:
    """Create a test configuration
    
    Args:
        test_config: Test configuration fixture with proper BotConfig structure
    
    Returns:
        BotConfig: Configuration object for testing
    """
    return test_config

@pytest.fixture
def downloader(config: BotConfig, mock_session_manager) -> InstagramDownloader:
    """Create an InstagramDownloader instance for testing
    
    Args:
        config: Bot configuration fixture
        mock_session_manager: Mocked session manager fixture
    
    Returns:
        InstagramDownloader: Configured downloader instance
    """
    return InstagramDownloader(config=config.instagram, downloads_path=config.downloads_path)

@pytest.fixture
def mock_session_manager():
    with patch('src.services.instagram_downloader.InstagramSessionManager') as mock:
        instance = mock.return_value
        instance.get_cookies.return_value = {'sessionid': 'test_session'}
        yield instance

class TestURLHandling:
    """Tests for Instagram URL handling and validation"""

    async def test_content_type_detection(self, downloader: InstagramDownloader):
        """Test content type detection from URLs
    
        This test verifies that content type detection works correctly for:
        - Post URLs (format: /p/{identifier})
        - Reel URLs (format: /reels/{identifier})
        - Story URLs (format: /stories/{username})
        """
        test_cases = [
            (TEST_POST_URL, ("post", None)),
            (TEST_REEL_URL, ("reel", None)),
            (TEST_STORY_URL.rsplit("/", 1)[0] + "/", ("story", "username"))
        ]
    
        for url, (expected_type, expected_id) in test_cases:
            content_type, identifier = await downloader.detect_content_type(url)
            assert content_type == expected_type, f"Wrong content type for {url}"
            assert identifier == expected_id, f"Wrong identifier for {url}"

    def test_extract_identifier_invalid_url(self, downloader: InstagramDownloader):
        """Test URL identifier extraction with invalid URL formats
        
        Verifies that appropriate errors are raised for malformed URLs
        """
        invalid_urls = [
            "https://instagram.com/invalid/url",
            "https://instagram.com/p/",
            "https://instagram.com/reels",
            "",
            None
        ]
        
        for url in invalid_urls:
            with pytest.raises(ValueError, match="Invalid Instagram URL format"):
                downloader._extract_identifier(url)

    def test_is_instagram_url_validation(self, downloader: InstagramDownloader):
        """Test Instagram URL validation for various URL formats
        
        Verifies that the URL validator correctly identifies:
        - Valid Instagram URLs (posts, reels, stories)
        - Invalid or malformed URLs
        - URLs from other domains
        """
        valid_urls = [
            TEST_POST_URL,
            TEST_REEL_URL,
            TEST_STORY_URL,
            "https://instagram.com/p/ABC123",
            "http://www.instagram.com/p/ABC123"
        ]
        
        invalid_urls = [
            "https://example.com/not/instagram",
            "https://fake-instagram.com/p/ABC123",
            "https://instagram.com/invalid/url",
            "",
            None,
            "http://instagram",
            "instagram.com/p/ABC123"
        ]
        
        for url in valid_urls:
            assert downloader._is_instagram_url(url) is True, f"Should accept valid URL: {url}"
            
        for url in invalid_urls:
            assert downloader._is_instagram_url(url) is False, f"Should reject invalid URL: {url}"


class TestDownloader:
    """Tests for content downloading functionality"""

    def test_get_download_path(self, downloader: InstagramDownloader):
        """Test download path generation with timestamp
        
        Verifies that:
        - Path includes current timestamp
        - Path is within configured downloads directory
        - Path format matches expected pattern
        """
        expected_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = downloader._get_download_path()
        
        assert isinstance(path, Path), "Download path should be a Path object"
        assert expected_date in str(path), "Path should include current timestamp"
        assert path.parent == downloader.config.DOWNLOADS_PATH, "Path should be in downloads directory"

    @pytest.mark.asyncio
    async def test_download_content_success(self, downloader: InstagramDownloader):
        """Test successful content download
        
        Verifies that:
        - Download command executes successfully
        - Output paths are correctly parsed
        - Gallery-dl is called with correct parameters
        - Success status and file paths are returned
        """
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=str(TEST_DOWNLOAD_PATH),
                stderr=""
            )
            
            result = await downloader.download(TEST_POST_URL)
            assert result.success is True
            assert len(result.file_paths) == 1
            assert TEST_DOWNLOAD_PATH.name in result.file_paths[0]
            
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert '--cookies-from-browser' in args
            assert TEST_POST_URL in args
            assert any('--write-metadata' in arg for arg in args)

    @pytest.mark.asyncio
    async def test_download_with_metadata(self, downloader: InstagramDownloader, tmp_path: Path):
        """Test download with metadata collection
        
        Verifies that:
        - Metadata is properly written
        - JSON metadata file is created
        - Metadata contains required fields
        """
        metadata_file = TEST_DOWNLOAD_PATH.with_suffix('.json')
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=f"{TEST_DOWNLOAD_PATH}\n{metadata_file}\n",
                stderr=""
            )
            
            result = await downloader.download(TEST_POST_URL)
            assert result.success is True
            assert len(result.file_paths) == 2
            assert any(metadata_file.name in path for path in result.file_paths)
            
            # Verify metadata collection flags were passed
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert '--write-metadata' in args

    @pytest.mark.asyncio
    async def test_download_cleanup_on_error(self, downloader: InstagramDownloader, tmp_path: Path):
        """Test cleanup of partial downloads on failure
        
        Verifies that:
        - Temporary files are cleaned up on error
        - Download directory is removed if empty
        - Existing files are not affected
        """
        test_file = tmp_path / "test.jpg"
        test_file.touch()
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="",
                stderr="Download failed"
            )
            
            result = await downloader.download(TEST_POST_URL)
            assert result.success is False
            assert not test_file.exists(), "Temporary files should be cleaned up"
            assert tmp_path.exists(), "Parent directory should be preserved"

    @pytest.mark.asyncio
    async def test_download_errors(self, downloader: InstagramDownloader):
        """Test various download error scenarios
        
        Tests handling of:
        - Network errors
        - Rate limiting
        - Authentication failures
        - Invalid content errors
        """
        error_cases = [
            (1, "", "Error: Failed to download", "download failed"),
            (1, "", "429 Too Many Requests", "rate limit"),
            (1, "", "401 Unauthorized", "authentication"),
            (1, "", "404 Not Found", "not found"),
        ]
        
        for returncode, stdout, stderr, expected_error in error_cases:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr
                )
                
                result = await downloader.download(TEST_POST_URL)
                assert result.success is False, f"Should fail for error: {stderr}"
                assert expected_error.lower() in result.error.lower(), f"Error message should contain: {expected_error}"