#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting Instagram Telegram Bot Setup with Persistent Sessions...${NC}"

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

# Function to check if bot is running and has persistent sessions
check_bot_status() {
    local max_attempts=60  # Increased to 2 minutes
    local attempt=0
    
    echo -e "${YELLOW}Checking bot startup and session status...${NC}"
    
    while [ $attempt -lt $max_attempts ]; do
        # Check for successful initialization
        if docker compose logs bot 2>/dev/null | grep -q "Bot initialized successfully with persistent sessions"; then
            echo -e "${GREEN}Bot started successfully with persistent sessions!${NC}"
            return 0
        fi
        
        # Check if bot is waiting for authentication
        if docker compose logs bot 2>/dev/null | grep -q "Starting Telegram authentication"; then
            echo -e "${YELLOW}Bot is waiting for authentication input...${NC}"
            return 1
        fi
        
        # Check for initialization failure
        if docker compose logs bot 2>/dev/null | grep -q "Failed to initialize"; then
            echo -e "${RED}Bot initialization failed. Check logs for details.${NC}"
            docker compose logs --tail=20 bot
            return 2
        fi
        
        sleep 2
        attempt=$((attempt + 1))
        echo -n "."
    done
    
    echo -e "${RED}Timeout waiting for bot to start${NC}"
    return 3
}

# Function to handle interactive authentication
handle_authentication() {
    echo -e "${YELLOW}Bot needs Telegram authentication...${NC}"
    echo -e "${RED}*** IMPORTANT INSTRUCTIONS ***${NC}"
    echo -e "${YELLOW}The bot will prompt for your phone number and verification code.${NC}"
    echo -e "${YELLOW}This is a ONE-TIME setup that will be saved permanently.${NC}"
    echo -e "${RED}*** Follow the prompts carefully ***${NC}"
    echo ""
    
    # Stop the detached container
    echo -e "${YELLOW}Stopping detached container...${NC}"
    $DOCKER_COMPOSE_BIN down
    
    # Start in interactive mode for authentication
    echo -e "${YELLOW}Starting authentication process...${NC}"
    echo -e "${YELLOW}Enter your information when prompted by the bot.${NC}"
    echo ""
    
    # Run interactively
    $DOCKER_COMPOSE_BIN run --rm -it bot python bot.py
    
    # Check if authentication was successful by looking for session file
    if [ -f "sessions/telegram_bot_session.session" ]; then
        echo -e "${GREEN}Authentication successful! Session file created.${NC}"
        return 0
    else
        echo -e "${RED}Authentication may have failed - no session file found.${NC}"
        echo -e "${YELLOW}The bot will attempt to use database-stored session on next start.${NC}"
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

echo -e "${YELLOW}Starting bot with persistent session management...${NC}"
$DOCKER_COMPOSE_BIN up -d

# Wait a moment for container to start
sleep 5

# Check bot status
check_bot_status
exit_code=$?

case $exit_code in
    0)
        echo -e "${GREEN}=== Setup completed successfully! ===${NC}"
        echo -e "${GREEN}Bot is running with persistent Telegram sessions.${NC}"
        ;;
    1)
        echo -e "${YELLOW}Bot requires authentication...${NC}"
        if handle_authentication; then
            # Start in detached mode after successful auth
            echo -e "${YELLOW}Starting bot in background...${NC}"
            $DOCKER_COMPOSE_BIN up -d
            
            # Verify it's working
            sleep 5
            if check_bot_status; then
                echo -e "${GREEN}=== Setup completed successfully! ===${NC}"
                echo -e "${GREEN}Bot is now running with persistent sessions.${NC}"
            else
                echo -e "${YELLOW}Authentication completed but bot status unclear.${NC}"
                echo -e "${YELLOW}Check logs: docker compose logs -f${NC}"
            fi
        else
            echo -e "${YELLOW}Authentication completed. Starting bot...${NC}"
            $DOCKER_COMPOSE_BIN up -d
            sleep 5
            echo -e "${YELLOW}Bot may be starting up. Monitor logs: docker compose logs -f${NC}"
        fi
        ;;
    2)
        echo -e "${RED}Bot initialization failed.${NC}"
        echo -e "${RED}Please check the error messages above and fix any issues.${NC}"
        exit 1
        ;;
    3)
        echo -e "${YELLOW}Bot startup status unclear. Checking current status...${NC}"
        if docker compose ps | grep -q "Up"; then
            echo -e "${YELLOW}Container is running. Check logs for details:${NC}"
            echo -e "${YELLOW}docker compose logs -f${NC}"
        else
            echo -e "${RED}Container failed to start. Check logs:${NC}"
            docker compose logs --tail=30 bot
            exit 1
        fi
        ;;
esac

echo -e "${YELLOW}=== Useful Commands ===${NC}"
echo -e "View logs:      $DOCKER_COMPOSE_BIN logs -f"
echo -e "Stop bot:       $DOCKER_COMPOSE_BIN down"
echo -e "Restart bot:    $DOCKER_COMPOSE_BIN restart"
echo -e "Bot status:     $DOCKER_COMPOSE_BIN ps"
echo -e "Session status: Send /telegram_status to your bot"

# Show current status
echo -e "${YELLOW}=== Current Status ===${NC}"
$DOCKER_COMPOSE_BIN ps

echo -e "${GREEN}=== Setup Summary ===${NC}"
echo -e "✅ Directories created with proper permissions"
echo -e "✅ Database migrations applied" 
echo -e "✅ Docker containers built and started"
echo -e "✅ Telegram sessions are now persistent across restarts"
echo -e ""
echo -e "${YELLOW}Next time you restart, the bot will automatically use the stored session!${NC}"