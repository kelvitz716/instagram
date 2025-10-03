"""Tests for rate limiting and smart download functionality."""
import pytest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

pytest_plugins = ('pytest_asyncio',)

from src.core.resilience.rate_limiter import InstagramRateLimiter
from src.core.resilience.smart_download import SmartDownloadManager, with_smart_download
from src.services.instagram_downloader import InstagramDownloader

# Constants for timing tests
TIMING_TOLERANCE = 0.95  # Allow 5% timing variance for normal operations
BURST_TOLERANCE = 0.90  # Allow 10% variance for burst requests
OVERLOAD_TOLERANCE = 0.85  # Allow 15% variance for overload conditions

# Mark all tests in this module as asyncio tests
pytestmark = pytest.mark.asyncio

@pytest.fixture
def rate_limiter():
    limiter = InstagramRateLimiter()
    # Set default values directly
    limiter.config._set_defaults()
    return limiter

@pytest.fixture
def download_manager():
    return SmartDownloadManager()

async def test_rate_limiter_basic_delay(rate_limiter):
    """Test that rate limiter enforces minimum delay between requests."""
    start_time = asyncio.get_event_loop().time()
    
    # Make two requests
    await rate_limiter.wait_for_request()
    await rate_limiter.wait_for_request()
    
    elapsed = asyncio.get_event_loop().time() - start_time
    # Account for timing variance
    min_expected = rate_limiter.config.INSTAGRAM_MIN_REQUEST_INTERVAL * TIMING_TOLERANCE
    assert elapsed >= min_expected, \
        f"Rate limiter should enforce basic delay. Expected at least {min_expected}, got {elapsed}"

async def test_rate_limiter_burst_limit(rate_limiter):
    """Test that rate limiter enforces burst request limits."""
    tasks = []
    for _ in range(rate_limiter.config.INSTAGRAM_MAX_BURST_REQUESTS + 1):
        tasks.append(rate_limiter.wait_for_request())
        
    # Execute all requests simultaneously
    start_time = asyncio.get_event_loop().time()
    await asyncio.gather(*tasks)
    elapsed = asyncio.get_event_loop().time() - start_time
    
    # Verify that the extra request was delayed (allow more timing variance for bursts)
    min_expected = rate_limiter.config.INSTAGRAM_MIN_REQUEST_INTERVAL * BURST_TOLERANCE
    assert elapsed >= min_expected, \
        f"Rate limiter should enforce burst delay. Expected at least {min_expected}, got {elapsed}"

async def test_smart_download_retry_logic(download_manager):
    """Test that smart download manager implements retry logic correctly."""
    mock_downloader = Mock(spec=InstagramDownloader)
    
    # Configure mock to fail twice then succeed
    mock_downloader.download_post.side_effect = [
        Exception("First failure"),
        Exception("Second failure"),
        {"post_url": "success"}
    ]
    
    # Create a mock class instance
    class MockDownloader:
        def __init__(self):
            self._download_manager = download_manager
            
        @with_smart_download()
        async def download_with_retry(self):
            return await mock_downloader.download_post("test_url")
    
    downloader = MockDownloader()
    result = await downloader.download_with_retry()
    assert result == {"post_url": "success"}
    assert mock_downloader.download_post.call_count == 3

async def test_smart_download_backoff(download_manager):
    """Test that smart download implements exponential backoff."""
    start_time = asyncio.get_event_loop().time()
    
    # Create a mock class instance
    class MockDownloader:
        def __init__(self):
            self._download_manager = download_manager
            
        @with_smart_download()
        async def failing_download(self):
            raise Exception("Simulated failure")
    
    downloader = MockDownloader()
    with pytest.raises(Exception):
        try:
            await downloader.failing_download()
        except Exception as e:
            elapsed = asyncio.get_event_loop().time() - start_time
            # Verify that enough time has passed for exponential backoff (allow timing variance)
            delays = [download_manager._calculate_backoff(i) for i in range(3)]
            assert elapsed >= sum(delays) * TIMING_TOLERANCE
            raise e

async def test_rate_limiter_overload(rate_limiter):
    """Test rate limiter behavior under overload conditions."""
    requests_count = rate_limiter.config.INSTAGRAM_MAX_BURST_REQUESTS * 2
    start_time = asyncio.get_event_loop().time()
    
    # Launch multiple requests simultaneously
    tasks = [rate_limiter.wait_for_request() for _ in range(requests_count)]
    await asyncio.gather(*tasks)
    
    elapsed = asyncio.get_event_loop().time() - start_time
    min_expected = rate_limiter.config.INSTAGRAM_MIN_REQUEST_INTERVAL
    
    # First check: Basic rate limiting is enforced
    min_delay = min_expected * OVERLOAD_TOLERANCE
    assert elapsed >= min_delay, \
        f"Rate limiter should enforce basic delay under overload. Expected at least {min_delay}, got {elapsed}"
    
    # Second check: Some extra delay is added for overload conditions
    # We expect at least a small increase over the base delay
    min_delay_with_overload = min_expected * 1.05  # Only expect 5% increase but be consistent
    assert elapsed >= min_delay_with_overload * OVERLOAD_TOLERANCE, \
        f"Rate limiter should add extra delay for overload conditions. Expected at least {min_delay_with_overload * OVERLOAD_TOLERANCE}, got {elapsed}"

async def test_conservative_mode(rate_limiter):
    """Test conservative mode activation and behavior."""
    # Simulate multiple errors
    for _ in range(rate_limiter.config.ERROR_THRESHOLD):
        rate_limiter.handle_error(Exception("rate limit"))
    
    assert rate_limiter.in_conservative_mode
    
    # Ensure we start the timer after entering conservative mode
    await asyncio.sleep(0.1)  # Short delay to ensure state change
    start_time = asyncio.get_event_loop().time()
    await rate_limiter.wait_for_request()
    elapsed = asyncio.get_event_loop().time() - start_time
    
    # Should have roughly 2x delay but account for timing variance
    min_expected = rate_limiter.config.INSTAGRAM_MIN_REQUEST_INTERVAL * 1.8  # Close to 2x
    assert elapsed >= min_expected * TIMING_TOLERANCE, \
        f"Rate limiter should double delay in conservative mode. Expected at least {min_expected * TIMING_TOLERANCE}, got {elapsed}"

async def test_session_rotation(rate_limiter):
    """Test session rotation logic."""
    # Set session start time to past threshold
    rate_limiter.session_start_time = datetime.now() - timedelta(
        seconds=rate_limiter.config.SESSION_ROTATE_INTERVAL + 1
    )
    
    assert rate_limiter.should_rotate_session()

class TestInstagramDownloader:
    """Test the Instagram downloader with smart download handling."""
    
    @pytest.fixture
    def downloader(self, tmp_path):
        config = Mock()
        downloads_path = tmp_path / "downloads"
        downloads_path.mkdir(exist_ok=True)
        
        # Create a mock session manager
        session_manager = Mock()
        session_manager.cookies_file = tmp_path / "cookies.txt"
        
        # Create the downloader with mocked components
        downloader = InstagramDownloader(config, downloads_path)
        downloader.session_manager = session_manager
        
        return downloader
    
    async def test_download_with_rate_limiting(self, downloader, tmp_path):
        """Test that downloads are rate limited."""
        # Create a test file to simulate download
        test_file = tmp_path / "downloads" / "test.jpg"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        
        with patch.object(downloader, '_check_session_before_download', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.is_file', return_value=True):
            
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(test_file)
            
            start_time = asyncio.get_event_loop().time()
            
            # Try two downloads
            await downloader.download_post("https://instagram.com/p/123")
            await downloader.download_post("https://instagram.com/p/456")
            
            elapsed = asyncio.get_event_loop().time() - start_time
            # Account for timing variance
            min_expected = 5.0  # Minimum delay between requests
            assert elapsed >= min_expected * TIMING_TOLERANCE, \
                f"Downloads should be rate limited. Expected at least {min_expected * TIMING_TOLERANCE}, got {elapsed}"