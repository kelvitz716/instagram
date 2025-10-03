#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if setup has already been completed
if [ -f ".setup_complete" ]; then
    echo -e "${YELLOW}Setup has already been completed!${NC}"
    echo -e "${YELLOW}If you need to run setup again, delete the .setup_complete file${NC}"
    echo -e "\n${GREEN}=== Quick Reference Commands ===${NC}"
    echo -e "Start bot:      docker compose up -d"
    echo -e "Stop bot:       docker compose down"
    echo -e "View logs:      docker compose logs -f"
    echo -e "Restart bot:    docker compose restart"
    echo -e "Check status:   docker compose ps"
    exit 0
fi

echo -e "${YELLOW}Starting Instagram Telegram Bot Initial Setup...${NC}"

# --- Setup Docker Compose Command for Backward Compatibility ---

DOCKER_COMPOSE_BIN=""

if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker compose"
    echo -e "${GREEN}Using 'docker compose' (v2) syntax.${NC}"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker-compose"
    echo -e "${GREEN}Using 'docker-compose' (v1) syntax.${NC}"
else
    echo -e "${RED}Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

# Create all required directories with proper permissions
echo -e "${YELLOW}Creating required directories...${NC}"
mkdir -p downloads data/db sessions uploads temp telegram

# Set proper permissions
chmod -R 777 sessions data
chmod 755 downloads uploads temp telegram

# Create database file
touch data/bot_data.db
chmod 666 data/bot_data.db

echo -e "${GREEN}Created directory structure with proper permissions:${NC}"
echo -e "  - downloads/: For downloaded media"
echo -e "  - data/: For database and persistent data (chmod 777)"
echo -e "  - sessions/: For Telegram session files (chmod 777)"
echo -e "  - uploads/: For processed files ready to upload"
echo -e "  - temp/: For temporary files"
echo -e "  - telegram/: For Telegram-related files"

# Run database migration
echo -e "${YELLOW}Running database migrations...${NC}"
if [ -f "migrate.py" ]; then
    python3 migrate.py || {
        echo -e "${RED}Database migration failed${NC}"
        exit 1
    }
    echo -e "${GREEN}Database migrations completed${NC}"
else
    echo -e "${YELLOW}No migration script found, skipping...${NC}"
fi

# Check for environment variables
echo -e "${YELLOW}Checking configuration...${NC}"
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo -e "${YELLOW}Please create a .env file with the following variables:${NC}"
    echo -e "BOT_TOKEN=your_bot_token"
    echo -e "API_ID=your_api_id" 
    echo -e "API_HASH=your_api_hash"
    echo -e "TARGET_CHAT_ID=your_chat_id"
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

# Validate required environment variables
REQUIRED_VARS=("BOT_TOKEN" "API_ID" "API_HASH")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    printf '%s\n' "${MISSING_VARS[@]}"
    exit 1
fi

# Function to check if session exists and is valid
check_session() {
    if [ -f "sessions/telegram_bot_session.session" ] && [ -s "sessions/telegram_bot_session.session" ]; then
        echo -e "${GREEN}Valid Telegram session found!${NC}"
        return 0
    else
        echo -e "${YELLOW}No valid Telegram session found${NC}"
        return 1
    fi
}

# Main setup logic
echo -e "${YELLOW}Building Docker containers...${NC}"
$DOCKER_COMPOSE_BIN build --pull

if [ $? -ne 0 ]; then
    echo -e "${RED}Docker build failed. Please check your Dockerfile and try again.${NC}"
    exit 1
fi

# Run Telegram authentication
echo -e "${YELLOW}Starting Telegram authentication process...${NC}"
chmod +x telegram_auth.sh
./telegram_auth.sh

if [ $? -ne 0 ]; then
    echo -e "${RED}Telegram authentication failed. Please try again.${NC}"
    exit 1
fi

# Verify session file one last time
if ! check_session; then
    echo -e "${RED}Failed to verify Telegram session. Please run setup.sh again.${NC}"
    exit 1
fi

# Start the bot in detached mode
echo -e "${YELLOW}Starting bot in detached mode...${NC}"
$DOCKER_COMPOSE_BIN up -d

# Create setup complete marker
touch .setup_complete

echo -e "${GREEN}=== Initial setup completed successfully! ===${NC}"
echo -e "${GREEN}Bot is running with persistent Telegram sessions.${NC}"

echo -e "\n${GREEN}=== Setup Summary ===${NC}"
echo -e "✅ Directories created with proper permissions"
echo -e "✅ Database migrations applied" 
echo -e "✅ Telegram authentication completed"
echo -e "✅ Session file saved in sessions/telegram_bot_session.session"
echo -e "✅ Docker containers built and started"

echo -e "\n${YELLOW}=== Important Information ===${NC}"
echo -e "Your Telegram session is saved in: sessions/telegram_bot_session.session"
echo -e "This file is crucial for authentication - DO NOT delete it!"
echo -e "The sessions directory is persistent and will preserve your login"

echo -e "\n${GREEN}=== Daily Usage Commands ===${NC}"
echo -e "Start bot:      $DOCKER_COMPOSE_BIN up -d"
echo -e "Stop bot:       $DOCKER_COMPOSE_BIN down"
echo -e "View logs:      $DOCKER_COMPOSE_BIN logs -f"
echo -e "Restart bot:    $DOCKER_COMPOSE_BIN restart"
echo -e "Check status:   $DOCKER_COMPOSE_BIN ps"
echo -e "Check session:  Send /telegram_status to your bot"

# Show current status
echo -e "\n${YELLOW}=== Current Status ===${NC}"
$DOCKER_COMPOSE_BIN ps

echo -e "\n${GREEN}Setup is complete! The bot will use the stored session for all future starts.${NC}"
echo -e "${YELLOW}To run setup again in the future, delete the .setup_complete file${NC}"