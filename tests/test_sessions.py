#!/usr/bin/env python3
"""Test script for Instagram session."""
import asyncio
import logging
from pathlib import Path
from src.services.instagram_downloader import InstagramDownloader
from src.core.config import InstagramConfig
from src.core.session_manager import InstagramSessionError, InstagramSessionManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your Instagram username
INSTAGRAM_USERNAME = "kelvitz"

class SessionTester:
    def __init__(self):
        # Create basic config
        self.config = InstagramConfig()
        self.config.download_timeout = 60  # 60 seconds timeout
        self.config.username = INSTAGRAM_USERNAME
        
        # Initialize paths
        self.downloads_path = Path("downloads")
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        
    async def test_session(self):
        """Test Firefox session"""
        try:
            # Initialize session manager with cookies file
            cookies_file = Path("gallery-dl-cookies.txt")
            if not cookies_file.exists():
                print("\n❌ No cookies.txt file found. Please upload your Instagram cookies file first.")
                return False
                
            session_manager = InstagramSessionManager(self.downloads_path, cookies_file)
            browser_valid = session_manager.check_session()
            
            print("\n=== Session Status ===")
            print(f"Firefox Session: {'✅ Valid' if browser_valid else '❌ Invalid'}")
            print(f"Using Instagram username: {INSTAGRAM_USERNAME}")
            
            if not browser_valid:
                print("\n⚠️  Session Setup Instructions:")
                print("\nFor Firefox Session:")
                print("1. Open Firefox")
                print("2. Go to instagram.com")
                print("3. Log in to your account")
                print("4. Make sure to check 'Remember me' when logging in")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to test session: {e}")
            return False
    
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

def main():
    tester = SessionTester()
    asyncio.run(tester.run_tests())

if __name__ == "__main__":
    main()
