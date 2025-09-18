from typing import Dict, Any
import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, ANY, AsyncMock
import os
from pathlib import Path
from datetime import datetime
import subprocess

from src.services.instagram_downloader import (
    InstagramDownloader,
    InstagramDownloadError,
)
from src.core.config import BotConfig, InstagramConfig, TelegramConfig, UploadConfig
from src.core.session_manager import InstagramSessionManager, InstagramSessionError

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

@pytest_asyncio.fixture
async def mock_session_manager():
    with patch('src.services.instagram_downloader.InstagramSessionManager') as mock:
        instance = mock.return_value
        # Mock async methods
        instance._test_session = AsyncMock(return_value=(True, "Session is valid"))
        instance.get_cookies = AsyncMock(return_value={'sessionid': 'test_session'})
        instance._validate_cookies = AsyncMock(return_value=True)
        instance._find_downloaded_files = AsyncMock(return_value=[TEST_DOWNLOAD_PATH])
        yield instance

@pytest.mark.asyncio
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

    async def test_content_type_detection_invalid_url(self, downloader: InstagramDownloader):
        """Test content type detection with invalid URL formats
        
        Verifies that unknown content type is returned for malformed URLs
        """
        invalid_urls = [
            "https://instagram.com/invalid/url",
            "https://instagram.com/p/",
            "https://instagram.com/reels",
            "",
            None,
            "https://example.com/not/instagram",
            "instagram.com/p/ABC123"  # Must start with http(s)://
        ]
        
        for url in invalid_urls:
            if url is not None:
                content_type, identifier = await downloader.detect_content_type(url)
                assert content_type == "unknown", f"Should return unknown for invalid URL: {url}"
                assert identifier is None, f"Should have no identifier for invalid URL: {url}"

    async def test_username_extraction(self, downloader: InstagramDownloader):
        """Test username extraction from URLs
        
        Verifies that usernames are correctly extracted from:
        - Profile URLs
        - Post URLs
        - Story URLs
        """
        test_cases = [
            ("https://www.instagram.com/testuser/", "testuser"),
            ("https://instagram.com/testuser/p/ABC123/", "testuser"),
            ("https://instagram.com/testuser", "testuser"),
            ("@testuser", "testuser"),
            ("https://instagram.com/explore/", None),
            ("https://example.com/testuser", None)
        ]
        
        # Test invalid URLs as well
        invalid_urls = [
            "https://example.com/not/instagram",
            "ftp://instagram.com/user",
            "http://fake-instagram.com/user",
            None,
            "",
            "   "
        ]

        for url, expected_username in test_cases:
            username = await downloader.extract_username_from_url(url)
            assert username == expected_username, f"Wrong username for URL: {url}"
            
        for url in invalid_urls:
            if url is not None:
                assert await downloader.extract_username_from_url(url) is None, f"Should return None for invalid URL: {url}"


@pytest.mark.asyncio
class TestDownloader:
    """Tests for content downloading functionality"""

    @pytest.mark.asyncio
    async def test_post_download_success(self, downloader: InstagramDownloader):
        """Test successful post download
        
        Verifies that:
        - Post download executes successfully
        - Output paths are correctly returned
        - Gallery-dl is called with correct parameters
        """
        with patch('subprocess.run') as mock_run:
            # Set up mock subprocess call that simulates successful download
            mock_run.return_value = Mock(
                returncode=0,
                stdout=str(TEST_DOWNLOAD_PATH),
                stderr=""
            )

            # Mock the _find_downloaded_files method to return our test file
            with patch.object(downloader, '_find_downloaded_files', return_value=[TEST_DOWNLOAD_PATH]):
                files = await downloader.download_post(TEST_POST_URL)
                assert len(files) == 1
                assert TEST_DOWNLOAD_PATH.name == files[0].name
            
            # Verify gallery-dl was called with correct arguments
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert str(downloader.gallery_dl_path) == args[0]
            assert '--cookies-from-browser' in args
            assert TEST_POST_URL in args

    @pytest.mark.asyncio
    async def test_story_download_success(self, downloader: InstagramDownloader):
        """Test successful story download
        
        Verifies that:
        - Story download executes successfully
        - Uses yt-dlp for stories
        - Output paths are correctly returned
        """
        username = "testuser"
        with patch('subprocess.run') as mock_run:
            # Set up mock subprocess call that simulates successful download
            mock_run.return_value = Mock(
                returncode=0,
                stdout=str(TEST_DOWNLOAD_PATH),
                stderr=""
            )
            
            # Mock the _find_downloaded_files method to return our test file
            with patch.object(downloader, '_find_downloaded_files', return_value=[TEST_DOWNLOAD_PATH]):
                files = await downloader.download_story(username)
                assert len(files) == 1
                assert TEST_DOWNLOAD_PATH.name == files[0].name
            
            # Verify yt-dlp was used
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert str(downloader.yt_dlp_path) == args[0]
            assert '--cookies-from-browser' in args
            assert username in args[0]

    @pytest.mark.asyncio
    async def test_unified_download_content(self, downloader: InstagramDownloader):
        """Test unified content download method
        
        Verifies that:
        - Content type is properly detected
        - Appropriate download method is called
        - Returns correct file paths
        """
        with patch('subprocess.run') as mock_run:
            # Set up mock subprocess call that simulates successful download
            mock_run.return_value = Mock(
                returncode=0,
                stdout=str(TEST_DOWNLOAD_PATH),
                stderr=""
            )
            
            # Mock the _find_downloaded_files method to return our test file
            with patch.object(downloader, '_find_downloaded_files', return_value=[TEST_DOWNLOAD_PATH]):
                # Test post download
                files = await downloader.download_content(TEST_POST_URL)
                assert len(files) == 1
                assert TEST_DOWNLOAD_PATH.name == files[0].name

            # Verify gallery-dl was called
            mock_run.assert_called()
            args = mock_run.call_args[0][0]
            assert str(downloader.gallery_dl_path) == args[0]
            assert TEST_POST_URL in args

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
            
            with pytest.raises(InstagramDownloadError):
                await downloader.download_content(TEST_POST_URL)
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
                
                with pytest.raises(InstagramDownloadError) as exc_info:
                    await downloader.download_content(TEST_POST_URL)
                assert expected_error.lower() in str(exc_info.value).lower(), f"Error message should contain: {expected_error}"