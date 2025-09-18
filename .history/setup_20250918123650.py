from setuptools import setup, find_packages

setup(
    name="instagram-downloader-bot",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'python-telegram-bot',
        'gallery-dl',
        'browser-cookie3',
        'requests',
        'telethon',
        'yt-dlp',
    ],
)