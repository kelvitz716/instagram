#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting Instagram Telegram Bot Setup...${NC}"

# Check for docker and docker-compose
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

# Check for docker compose (both new and old syntax)
if ! (command -v docker-compose &> /dev/null || docker compose version &> /dev/null); then
    echo -e "${RED}Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

# Check for required files
if [ ! -f ".env" ]; then
    if [ -f "example.env" ]; then
        echo -e "${YELLOW}Creating .env file from example.env${NC}"
        cp example.env .env
        echo -e "${GREEN}Created .env file. Please edit it with your configuration.${NC}"
    else
        echo -e "${RED}No .env or example.env file found!${NC}"
        exit 1
    fi
fi

if [ ! -f "gallery-dl-cookies.txt" ]; then
    echo -e "${RED}No gallery-dl-cookies.txt file found!${NC}"
    echo -e "${YELLOW}Please create gallery-dl-cookies.txt with your Instagram cookies.${NC}"
    exit 1
fi

# Create all required directories with proper permissions
echo -e "${YELLOW}Creating required directories...${NC}"

# Create directories
mkdir -p downloads data/db sessions uploads temp telegram
chmod -R 777 data  # Ensure database directory is fully writable
chmod 775 downloads sessions uploads temp telegram

# Set up proper ownership (try to match container's botuser)
if getent group botuser > /dev/null 2>&1; then
    BOTGROUP="botuser"
else
    # If botuser group doesn't exist, use the current user's group
    BOTGROUP=$(id -gn)
fi

if id botuser > /dev/null 2>&1; then
    BOTUSER="botuser"
else
    # If botuser doesn't exist, use the current user
    BOTUSER=$USER
fi

# Touch the database file to ensure it exists with proper permissions
touch data/bot_data.db
chmod 666 data/bot_data.db

# Attempt to set ownership, but don't fail if it doesn't work (might need sudo)
chown -R $BOTUSER:$BOTGROUP downloads data sessions uploads temp telegram 2>/dev/null || true

echo -e "${GREEN}Created directory structure:${NC}"
echo -e "  - downloads/: For downloaded media"
echo -e "  - data/: For database and persistent data"
echo -e "    - data/db/: For SQLite database"
echo -e "  - sessions/: For Telegram session files"
echo -e "  - uploads/: For processed files ready to upload"
echo -e "  - temp/: For temporary files"
echo -e "  - telegram/: For Telegram-related files"

# Build and start the containers
echo -e "${YELLOW}Building and starting Docker containers...${NC}"
if command -v docker-compose &> /dev/null; then
    docker-compose up --build -d
else
    docker compose up --build -d
fi

# Check if containers are running
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Setup completed successfully!${NC}"
    if command -v docker-compose &> /dev/null; then
        echo -e "${YELLOW}To view logs, run: docker-compose logs -f${NC}"
        echo -e "${YELLOW}To stop the bot, run: docker-compose down${NC}"
    else
        echo -e "${YELLOW}To view logs, run: docker compose logs -f${NC}"
        echo -e "${YELLOW}To stop the bot, run: docker compose down${NC}"
    fi
else
    echo -e "${RED}Setup failed. Please check the error messages above.${NC}"
    exit 1
fi