import pytest
from unittest.mock import Mock, patch
from src.bot import INSTAGRAM_URL_PATTERN, CONTENT_ICONS

def test_instagram_url_pattern():
    """Test the Instagram URL pattern matching"""
    # Valid URLs
    valid_urls = [
        "https://www.instagram.com/p/ABC123/",
        "https://instagram.com/p/ABC123/",
        "http://www.instagram.com/reels/DEF456/",
        "https://www.instagram.com/stories/username/789012/",
        "https://www.instagram.com/username",
    ]
    
    # Invalid URLs
    invalid_urls = [
        "https://notinstagram.com/p/ABC123/",
        "https://instagram.fake.com/p/ABC123/",
        "http://instagram",
        "random text",
    ]
    
    for url in valid_urls:
        assert INSTAGRAM_URL_PATTERN.match(url) is not None, f"Should match {url}"
        
    for url in invalid_urls:
        assert INSTAGRAM_URL_PATTERN.match(url) is None, f"Should not match {url}"

def test_content_icons():
    """Test content icons mapping"""
    # Verify all expected content types have icons
    expected_types = ['post', 'reel', 'story', 'highlight', 'profile', 'tv', 'unknown']
    for content_type in expected_types:
        assert content_type in CONTENT_ICONS, f"Missing icon for {content_type}"
        assert isinstance(CONTENT_ICONS[content_type], str), f"Icon for {content_type} should be string"
        assert len(CONTENT_ICONS[content_type]) > 0, f"Icon for {content_type} should not be empty"