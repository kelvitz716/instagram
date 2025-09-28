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

# Check for required files (Keeping this simple for brevity, assuming .env and cookies exist)

# Create all required directories with proper permissions
echo -e "${YELLOW}Creating required directories...${NC}"
mkdir -p downloads data/db sessions uploads temp telegram
chmod -R 777 data  # Ensure database directory is fully writable
chmod 775 downloads sessions uploads temp telegram
touch data/bot_data.db
chmod 666 data/bot_data.db

# Attempt to set ownership to the container's expected UID/GID (1000)
# This is crucial for Telethon/python to write to the volume.
chown -R 1000:1000 downloads data sessions uploads temp telegram 2>/dev/null || true

echo -e "${GREEN}Created directory structure and set ownership (attempted 1000:1000):${NC}"
echo -e "  - downloads/: For downloaded media"
echo -e "  - data/: For database and persistent data"
echo -e "    - data/db/: For SQLite database"
echo -e "  - sessions/: For Telegram session files"
echo -e "  - uploads/: For processed files ready to upload"
echo -e "  - temp/: For temporary files"
echo -e "  - telegram/: For Telegram-related files"

# Function to wait for a file to appear
wait_for_file() {
    local file="$1"
    local timeout=15 # Increased timeout to 15 seconds
    local counter=0
    echo -e "${YELLOW}Waiting for session file to sync: ${file}${NC}"
    while [ $counter -lt $timeout ]; do
        if [ -f "$file" ]; then
            return 0 # Success
        fi
        sleep 1
        counter=$((counter + 1))
        echo -n "."
    done
    echo -e "" # Newline after dots
    return 1 # Failure
}


# --- INTEGRATED SOLUTION FOR FIRST-RUN INTERACTIVE LOGIN ---
TELEGRAM_SESSION_FILE="sessions/telegram_bot_session.session"
SERVICE_NAME="bot" 

echo -e "${YELLOW}Checking for existing Telegram session file: ${TELEGRAM_SESSION_FILE}${NC}"

if [ ! -f "$TELEGRAM_SESSION_FILE" ]; then
    echo -e "${YELLOW}Session file not found! Running service '${SERVICE_NAME}' interactively for first-time login...${NC}"
    
    echo -e "${YELLOW}Please follow the prompts to enter your phone number and login code.${NC}"
    echo -e "${RED}*** IMPORTANT: After successfully signing in, WAIT for 'Application started' and then press CTRL+C/Cmd/C to save the session file and exit. ***${NC}"

    # 1. Build the container first
    echo -e "${YELLOW}Building Docker containers...${NC}"
    $DOCKER_COMPOSE_BIN build --pull
    
    # 2. Run the service interactively, explicitly as botuser (UID 1000)
    echo -e "${YELLOW}Executing interactive login as botuser (UID 1000)...${NC}"
    # The --user 1000 flag is critical here for permissions on the volume
    $DOCKER_COMPOSE_BIN run --rm -it --no-deps --user 1000 $SERVICE_NAME python bot.py
    
    # Check the exit status of the interactive run
    RUN_EXIT_CODE=$?
    
    # 3. Wait for the session file to appear/sync
    if wait_for_file "$TELEGRAM_SESSION_FILE"; then
        echo -e "${GREEN}------------------------------------------------------------${NC}"
        echo -e "${GREEN}Login successful. Telegram session file is confirmed to exist.${NC}"
        echo -e "${GREEN}------------------------------------------------------------${NC}"

        # 4. Start the full stack in detached mode
        echo -e "${YELLOW}Starting all services in detached mode...${NC}"
        $DOCKER_COMPOSE_BIN up -d
    else
        # Handle failure cases more clearly
        if [ $RUN_EXIT_CODE -eq 0 ]; then
            echo -e "${RED}Interactive login exited successfully (Exit Code: 0), but the session file was NOT found in '${TELEGRAM_SESSION_FILE}' after waiting 15 seconds.${NC}"
            echo -e "${RED}This is a persistent volume synchronization issue. Check your Docker volume configuration and host file system permissions for the 'sessions/' directory.${NC}"
        else
            echo -e "${RED}Interactive login failed or was interrupted (Exit Code: $RUN_EXIT_CODE). Session file was not created.${NC}"
        fi
        echo -e "${RED}The bot will not run correctly until a valid session is established. Please fix the session saving issue and try again.${NC}"
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
