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

if ! command -v docker-compose &> /dev/null; then
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

# Create downloads directory if it doesn't exist
mkdir -p downloads/sessions
echo -e "${GREEN}Created downloads directory structure${NC}"

# Build and start the containers
echo -e "${YELLOW}Building and starting Docker containers...${NC}"
docker-compose up --build -d

# Check if containers are running
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Setup completed successfully!${NC}"
    echo -e "${YELLOW}To view logs, run: docker-compose logs -f${NC}"
    echo -e "${YELLOW}To stop the bot, run: docker-compose down${NC}"
else
    echo -e "${RED}Setup failed. Please check the error messages above.${NC}"
    exit 1
fi