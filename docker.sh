#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color
YELLOW='\033[1;33m'

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}Error: Docker is not running${NC}"
        exit 1
    fi
}

# Function to display help
show_help() {
    echo "Instagram Bot Docker Management Script"
    echo
    echo "Usage: $0 [command]"
    echo
    echo "Commands:"
    echo "  start     - Start the bot container"
    echo "  stop      - Stop the bot container"
    echo "  restart   - Restart the bot container"
    echo "  logs      - Show container logs"
    echo "  build     - Rebuild the container"
    echo "  clean     - Remove container, images, and build cache (keeps data)"
    echo "  help      - Show this help message"
}

# Check if Docker is installed
if ! command -v docker > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

# Check Docker version for compose command
DOCKER_COMPOSE="docker compose"
if docker --version | grep -q "version 1"; then
    DOCKER_COMPOSE="docker-compose"
fi

# Process commands
case "$1" in
    "start")
        check_docker
        echo -e "${GREEN}Starting bot...${NC}"
        $DOCKER_COMPOSE up -d
        ;;
    "stop")
        check_docker
        echo -e "${YELLOW}Stopping bot...${NC}"
        $DOCKER_COMPOSE down
        ;;
    "restart")
        check_docker
        echo -e "${YELLOW}Restarting bot...${NC}"
        $DOCKER_COMPOSE restart
        ;;
    "logs")
        check_docker
        $DOCKER_COMPOSE logs -f
        ;;
    "build")
        check_docker
        echo -e "${GREEN}Building container...${NC}"
        $DOCKER_COMPOSE build --no-cache
        ;;
    "clean")
        check_docker
        echo -e "${YELLOW}Cleaning up containers and images...${NC}"
        $DOCKER_COMPOSE down --rmi all
        ;;
    "help"|*)
        show_help
        ;;
esac
