#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting Instagram Telegram Bot Setup...${NC}"

# --- Setup Docker Compose Command for Backward Compatibility ---

DOCKER_COMPOSE_BIN=""

# Check for new 'docker compose' (v2) first
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker compose"
    echo -e "${GREEN}Using 'docker compose' (v2) syntax.${NC}"
# Check for old 'docker-compose' (v1)
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker-compose"
    echo -e "${GREEN}Using 'docker-compose' (v1) syntax.${NC}"
else
    echo -e "${RED}Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

# Check for docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
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

# Touch the database file to ensure it exists with proper permissions
touch data/bot_data.db
chmod 666 data/bot_data.db

# --- Determine User/Group for Ownership ---
# Get the current user's UID and GID which defaults to 1000:1000 in the container
CURRENT_UID=$(id -u)
CURRENT_GID=$(id -g)

# The container user is hardcoded to 1000:1000 (botuser:botuser) in the Dockerfile
# We will use the host's current user/group if the ID matches, otherwise default to a safe value.

# Attempt to set ownership to the container's expected UID/GID (1000)
# Use 'chown 1000:1000' directly to align with the Dockerfile, 
# but suppress errors in case the user isn't root (or using sudo).
chown -R 1000:1000 downloads data sessions uploads temp telegram 2>/dev/null || true

echo -e "${GREEN}Created directory structure and set ownership (attempted 1000:1000):${NC}"
echo -e "  - downloads/: For downloaded media"
echo -e "  - data/: For database and persistent data"
echo -e "    - data/db/: For SQLite database"
echo -e "  - sessions/: For Telegram session files"
echo -e "  - uploads/: For processed files ready to upload"
echo -e "  - temp/: For temporary files"
echo -e "  - telegram/: For Telegram-related files"


# --- INTEGRATED SOLUTION FOR FIRST-RUN INTERACTIVE LOGIN ---
TELEGRAM_SESSION_FILE="sessions/telegram_bot_session.session"
# *** CORRECTED SERVICE NAME: Matches the 'bot:' definition in docker-compose.yml ***
SERVICE_NAME="bot" 

echo -e "${YELLOW}Checking for existing Telegram session file: ${TELEGRAM_SESSION_FILE}${NC}"

if [ ! -f "$TELEGRAM_SESSION_FILE" ]; then
    echo -e "${YELLOW}Session file not found! Running service '${SERVICE_NAME}' interactively for first-time login...${NC}"
    echo -e "${YELLOW}Please follow the prompts to enter your phone number and login code.${NC}"

    # 1. Build the container first (in case of updates)
    echo -e "${YELLOW}Building Docker containers...${NC}"
    # Use --pull to ensure the base image is the latest
    $DOCKER_COMPOSE_BIN build --pull
    
    # 2. Run the service interactively to complete the Telegram login
    # --rm removes the container after exit. -it keeps it interactive. --no-deps skips dependencies.
    # We pass 'python bot.py' explicitly to run the entrypoint command
    $DOCKER_COMPOSE_BIN run --rm -it --no-deps $SERVICE_NAME python bot.py

    # Check the exit status of the interactive run
    RUN_EXIT_CODE=$?
    
    # Wait a moment for the file system to sync
    sleep 2 

    if [ $RUN_EXIT_CODE -eq 0 ] && [ -f "$TELEGRAM_SESSION_FILE" ]; then
        echo -e "${GREEN}Login appears successful. Telegram session file created.${NC}"

        # 3. Start the full stack in detached mode
        echo -e "${YELLOW}Starting all services in detached mode...${NC}"
        # Start without --build since we just built it, unless explicitly needed
        $DOCKER_COMPOSE_BIN up -d
    else
        # Handle failure cases more clearly
        if [ $RUN_EXIT_CODE -eq 0 ]; then
            echo -e "${RED}Interactive login exited successfully (Exit Code: 0), but the session file was not found in '${TELEGRAM_SESSION_FILE}'.${NC}"
            echo -e "${RED}This suggests the Telegram login failed internally (e.g., incorrect phone number/code, flood wait) or was interrupted cleanly.${NC}"
        else
            echo -e "${RED}Interactive login failed or was interrupted (Exit Code: $RUN_EXIT_CODE). Session file was not created.${NC}"
        fi
        echo -e "${RED}The bot will not run correctly until a valid session is established. Please ensure you complete the login prompts successfully and try again.${NC}"
        exit 1
    fi

else
    echo -e "${GREEN}Existing session file found. Starting bot in detached mode with potential updates.${NC}"
    
    # Session file exists, so just build and run detached
    $DOCKER_COMPOSE_BIN up --build -d
fi

# --- Final Status Check ---
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Setup completed successfully!${NC}"
    echo -e "${YELLOW}To view logs, run: $DOCKER_COMPOSE_BIN logs -f${NC}"
    echo -e "${YELLOW}To stop the bot, run: $DOCKER_COMPOSE_BIN down${NC}"
else
    echo -e "${RED}Final 'up' failed. Please check the error messages above.${NC}"
    exit 1
fi
