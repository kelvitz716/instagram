# downloader.py

import instaloader
import sys
import os
from pathlib import Path

# --- Configuration ---
# Your Instagram username. The session file should be named after this.
# Example: "my_cool_username"
INSTAGRAM_USERNAME = "kelvitz" 

# Directory where files will be downloaded.
DOWNLOADS_PATH = Path("./downloads")

def download_post(url: str):
    """
    Downloads a single Instagram post using Instaloader.
    
    Args:
        url (str): The URL of the Instagram post.
    """
    print(f"Initializing Instaloader...")
    L = instaloader.Instaloader(
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="{date_utc}_UTC_{profile}_{shortcode}"
    )

    # --- Load Session ---
    # This is the critical part for private accounts.
    # It looks for a file named after your username.
    try:
        print(f"Attempting to load session for '{INSTAGRAM_USERNAME}'...")
        L.load_session_from_file(INSTAGRAM_USERNAME)
        print("Session loaded successfully.")
    except FileNotFoundError:
        print(f"Error: Session file for '{INSTAGRAM_USERNAME}' not found.")
        print("Please run 'instaloader --login=YOUR_INSTAGRAM_USERNAME' in your terminal first.")
        sys.exit(1)

    # --- Download Logic ---
    try:
        # Extract the shortcode (e.g., DNHGxtkMhWP) from the URL
        shortcode = url.strip().split("/")[-2]
        print(f"Found shortcode: {shortcode}")
        
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        
        print(f"Starting download for post by '{post.owner_username}'...")
        
        # Create the downloads directory if it doesn't exist
        DOWNLOADS_PATH.mkdir(exist_ok=True, parents=True)

        # Download the post into the target directory
        L.download_post(post, target=DOWNLOADS_PATH)
        
        print(f"Successfully downloaded post {shortcode}.")
        
    except instaloader.exceptions.InstaloaderException as e:
        print(f"An error occurred with Instaloader: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def main():
    """
    Main entry point for the script.
    """
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <instagram_url_1>")
        sys.exit(1)
    
    # This version handles one URL at a time for simplicity
    url_to_download = sys.argv[1]
    
    # Make sure to replace this with your actual username!
    if INSTAGRAM_USERNAME == "YOUR_INSTAGRAM_USERNAME":
        print("Error: Please edit the script and set the INSTAGRAM_USERNAME variable.")
        sys.exit(1)

    download_post(url_to_download)


if __name__ == '__main__':
    main()
