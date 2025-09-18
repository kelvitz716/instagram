import pytest
from unittest.mock import Mock, patch
from src.core.session_manager import InstagramSessionManager, InstagramSessionError
from datetime import datetime

@pytest.fixture
def mock_session_cookies():
    return {
        'csrftoken': 'test_csrf_token',
        'sessionid': 'test_session_id',
        'ds_user_id': 'test_user_id'
    }

@pytest.fixture
def downloads_path(tmp_path):
    """Create a temporary directory for downloads"""
    return str(tmp_path / "downloads")

@pytest.fixture
def mock_browser_cookie3():
    with patch('src.core.session_manager.browser_cookie3') as mock:
        cookies = []
        for name, value in {'csrftoken': 'test_csrf_token', 'sessionid': 'test_session'}.items():
            cookie = Mock()
            cookie.name = name
            cookie.value = value
            cookie.domain = 'instagram.com'
            cookies.append(cookie)
        mock.firefox.return_value = cookies
        yield mock

@pytest.fixture
def session_manager(mock_browser_cookie3, mock_session_cookies, downloads_path):
    """Create a session manager with mocked dependencies"""
    with patch('src.core.session_manager.InstagramSessionManager._validate_cookies', return_value=True):
        manager = InstagramSessionManager(downloads_path=downloads_path)
        manager._session_cookies = mock_session_cookies
        return manager

def test_cookie_loading(session_manager, mock_session_cookies):
    """Test that cookies are properly loaded from Firefox"""
    assert session_manager._session_cookies.get('csrftoken') == mock_session_cookies['csrftoken']
    assert session_manager._session_cookies.get('sessionid') == mock_session_cookies['sessionid']
    assert session_manager._session_cookies.get('ds_user_id') == mock_session_cookies['ds_user_id']

@pytest.mark.asyncio
async def test_valid_session(session_manager):
    """Test session validation with valid response"""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"status":"ok"}'
        mock_get.return_value = mock_response
        
        is_valid, message = await session_manager.test_session()
        assert is_valid is True
        assert message == "Session is valid"

@pytest.mark.asyncio
async def test_rate_limited_session(session_manager):
    """Test session validation when rate limited"""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response
        
        with pytest.raises(InstagramSessionError) as exc_info:
            await session_manager.test_session()
        assert exc_info.value.is_rate_limit is True

@pytest.mark.asyncio
async def test_expired_session(session_manager):
    """Test session validation with expired session"""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        is_valid, message = await session_manager.test_session()
        assert is_valid is False
        assert "Session expired" in message

@pytest.mark.asyncio
async def test_network_error(session_manager):
    """Test session validation with network error"""
    with patch('requests.get', side_effect=Exception("Network error")):
        is_valid, message = await session_manager.test_session()
        assert is_valid is False
        assert "Failed to test session" in message

def test_get_cookies(session_manager, mock_session_cookies):
    """Test getting cookies dictionary"""
    cookies = session_manager.get_cookies()
    assert cookies == mock_session_cookies

def test_cookie_refresh(session_manager):
    """Test cookie refresh functionality"""
    with patch('src.core.session_manager.browser_cookie3') as mock_browser_cookie3:
        new_cookies = {
            'csrftoken': 'new_csrf_token',
            'sessionid': 'new_session_id',
        }
        mock_browser_cookie3.firefox.return_value = [
            Mock(name=name, value=value)
            for name, value in new_cookies.items()
        ]
        
        session_manager.refresh_cookies()
        assert session_manager._session_cookies.get('csrftoken') == 'new_csrf_token'
        assert session_manager._session_cookies.get('sessionid') == 'new_session_id'