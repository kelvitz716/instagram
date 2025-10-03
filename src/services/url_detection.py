"""URL detection and validation service."""

import re
from dataclasses import dataclass
from typing import Optional, Tuple
from src.core.constants import INSTAGRAM_URL_PATTERN, URL_PATTERN

@dataclass
class ContentInfo:
    """Information about detected Instagram content."""
    type: str
    url: str
    source_id: str
    is_collection: bool = False

class URLDetectionService:
    """Service for detecting and validating Instagram URLs."""
    
    def extract_urls(self, text: str) -> list[str]:
        """Extract all URLs from text."""
        return URL_PATTERN.findall(text)
    
    def extract_instagram_urls(self, text: str) -> list[str]:
        """Extract Instagram URLs from text."""
        return INSTAGRAM_URL_PATTERN.findall(text)
    
    def analyze_url(self, url: str) -> Optional[ContentInfo]:
        """
        Analyze Instagram URL to determine content type and metadata.
        
        Args:
            url: The Instagram URL to analyze
            
        Returns:
            ContentInfo if URL is valid Instagram content, None otherwise
        """
        if not INSTAGRAM_URL_PATTERN.match(url):
            return None
            
        # Clean up the URL
        url = url.strip().rstrip('/')
        
        # Extract content type and ID
        parts = url.split('/')
        if len(parts) < 4:
            return None
            
        content_type = self._determine_content_type(parts)
        source_id = parts[-1]
        is_collection = 'carousel' in url.lower()
        
        return ContentInfo(
            type=content_type,
            url=url,
            source_id=source_id,
            is_collection=is_collection
        )
    
    def _determine_content_type(self, url_parts: list[str]) -> str:
        """Determine the type of Instagram content from URL parts."""
        type_indicators = {
            'p': 'post',
            'reel': 'reel',
            'stories': 'story',
            'highlights': 'highlight',
            'tv': 'tv'
        }
        
        for part in url_parts:
            if part in type_indicators:
                return type_indicators[part]
                
        # If no specific type found, check for profile
        if len(url_parts) == 4:
            return 'profile'
            
        return 'unknown'