"""Tests for Instagram session management."""
import asyncio
import logging
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from src.core.config import InstagramConfig
from src.core.session_manager import InstagramSessionError, InstagramSessionManager
from src.services.instagram_downloader import InstagramDownloader

# Configure logging
logger = logging.getLogger(__name__)

# Test configuration
INSTAGRAM_USERNAME = "test_user"  # Test Instagram username

# Mark all tests in this module as asyncio tests
pytestmark = pytest.mark.asyncio

@pytest.fixture
def temp_path(tmp_path):
    """Create a temporary directory for testing."""
    return tmp_path

@pytest.fixture
def config():
    """Create a test configuration."""
    config = InstagramConfig()
    config.download_timeout = 5  # Short timeout for tests
    config.username = "test_user"
    return config

@pytest.fixture
def cookies_file(temp_path):
    """Create a mock cookies file."""
    cookies_path = temp_path / "cookies.txt"
    cookies_path.write_text("test_cookies_content")
    return cookies_path

@pytest.fixture
def session_manager(temp_path, config, cookies_file):
    """Create a session manager instance."""
    downloads_path = temp_path / "downloads"
    downloads_path.mkdir()
    return InstagramSessionManager(downloads_path, cookies_file)

async def test_session_initialization(session_manager):
    """Test proper session manager initialization."""
    assert session_manager.downloads_path.exists()
    assert session_manager.cookies_file.exists()

async def test_session_validation(session_manager):
    """Test session validation with valid cookies."""
    with patch.object(session_manager, '_validate_cookies', return_value=True):
        assert await session_manager.check_session()

async def test_session_validation_failure(session_manager):
    """Test session validation with invalid cookies."""
    with patch.object(session_manager, '_validate_cookies', return_value=False):
        assert not await session_manager.check_session()

async def test_session_error_handling(session_manager):
    """Test error handling during session operations."""
    with patch.object(session_manager, '_validate_cookies', side_effect=InstagramSessionError("Invalid session")):
        with pytest.raises(InstagramSessionError, match="Invalid session"):
            await session_manager.check_session()

async def test_session_refresh(session_manager):
    """Test session refresh functionality."""
    with patch.object(session_manager, '_refresh_session') as mock_refresh:
        await session_manager.refresh_session()
        mock_refresh.assert_called_once()

async def test_session_cleanup(session_manager):
    """Test session cleanup."""
    with patch.object(session_manager, '_cleanup_session') as mock_cleanup:
        await session_manager.cleanup()
        mock_cleanup.assert_called_once()

async def test_manual_session_setup():
    """Test manual session setup instructions."""
    try:
        print("Manual Session Setup Instructions:")
        print("1. Clear your browser cookies")
        print("2. Go to instagram.com")
        print("3. Log in to your account")
        print("4. Make sure to check 'Remember me' when logging in")
        return False
    except Exception as e:
        logger.error(f"Failed to test session: {e}")
        return False
    return True
    
    async def run_tests(self):
        """Run all download tests"""
        try:
            print("\n🔄 Testing Instagram Session...")
            if not await self.test_session():
                print("\n❌ Session test failed. Please fix the session and try again.")
                return
            
            print("\n✅ Session validated successfully!")
            
            # Initialize downloader
            downloader = InstagramDownloader(self.config, self.downloads_path)
            
            # Test URLs
            tests = [
                {
                    "type": "Post/Reel",
                    "url": "https://www.instagram.com/reel/DNoA2UTuClw/",
                },
                {
                    "type": "Stories",
                    "url": f"https://www.instagram.com/stories/{INSTAGRAM_USERNAME}/",
                }
            ]
            
            print("\n=== Starting Download Tests ===")
            for test in tests:
                print(f"\n🧪 Testing {test['type']}")
                print(f"URL: {test['url']}")
                
                try:
                    if "/stories/" in test['url']:
                        username = test['url'].split("/stories/")[1].split("/")[0]
                        files = await downloader.download_stories(username)
                    else:
                        files = await downloader.download_post(test['url'])
                    
                    if files:
                        print(f"✅ Success! Downloaded {len(files)} files:")
                        for f in files:
                            print(f"  📄 {f.name}")
                    else:
                        print("⚠️  No files downloaded")
                        
                except InstagramSessionError as e:
                    print(f"❌ Session Error: {str(e)}")
                except Exception as e:
                    print(f"❌ Error: {str(e)}")
            
            print("\n=== Test Run Complete ===")
            
        except Exception as e:
            logger.error(f"Test run failed: {e}")
            print(f"\n❌ Test run failed: {e}")

if __name__ == "__main__":
    pytest.main([__file__])

if __name__ == "__main__":

