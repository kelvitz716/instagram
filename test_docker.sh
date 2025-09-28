#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting test container...${NC}"

# Stop any existing test container
docker stop instagram-bot-test 2>/dev/null
docker rm instagram-bot-test 2>/dev/null

# Create test directories
mkdir -p test_downloads/sessions

# Run container with test configuration
docker run -d \
    --name instagram-bot-test \
    -v $(pwd)/test_downloads:/app/downloads \
    -v $(pwd)/gallery-dl-cookies.txt:/app/gallery-dl-cookies.txt:ro \
    -v $(pwd)/test.env:/app/.env:ro \
    instagram-bot

# Wait for container to start
sleep 5

# Check container status
if [ "$(docker ps -q -f name=instagram-bot-test)" ]; then
    echo -e "${GREEN}Container started successfully!${NC}"
    
    # Show initial logs
    echo -e "${YELLOW}Initial logs:${NC}"
    docker logs instagram-bot-test
    
    # Check health status
    echo -e "\n${YELLOW}Health status:${NC}"
    docker inspect instagram-bot-test --format='{{.State.Health.Status}}'
    
    # Show how to access logs
    echo -e "\n${GREEN}Test container is running!${NC}"
    echo -e "To view logs: ${YELLOW}docker logs -f instagram-bot-test${NC}"
    echo -e "To stop: ${YELLOW}docker stop instagram-bot-test${NC}"
    echo -e "To remove: ${YELLOW}docker rm instagram-bot-test${NC}"
else
    echo -e "${RED}Container failed to start!${NC}"
    echo -e "${YELLOW}Logs:${NC}"
    docker logs instagram-bot-test
    exit 1
fi