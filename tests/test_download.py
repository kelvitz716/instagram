import asyncio
import logging
from pathlib import Path
from src.services.instagram_downloader import InstagramDownloader
from src.core.config import InstagramConfig

# Set up logging
logging.basicConfig(level=logging.INFO)

INSTAGRAM_USERNAME = "kelvitz"  # Replace with your username

async def main():
    # Create a basic config
    config = InstagramConfig()
    config.download_timeout = 60  # 60 seconds timeout
    config.username = INSTAGRAM_USERNAME
    
    # Initialize downloader
    downloads_path = Path("downloads")
    downloader = InstagramDownloader(config, downloads_path)
    
    # Test URLs - uncomment the one you want to test
    urls = [
        "https://www.instagram.com/reel/DNoA2UTuClw/",  # Replace with a post/reel URL
        "https://www.instagram.com/stories/orcwaifu/",  # Replace with a username that has stories
    ]
    
    for url in urls:
        print(f"\nTesting URL: {url}")
        try:
            if "/stories/" in url:
                username = url.split("/stories/")[1].split("/")[0]
                files = await downloader.download_stories(username)
            else:
                files = await downloader.download_post(url)
            
            if files:
                print(f"Successfully downloaded {len(files)} files:")
                for f in files:
                    print(f"  - {f}")
            else:
                print("No files downloaded")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
