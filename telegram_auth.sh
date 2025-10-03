#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check for environment variables
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
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

echo -e "${YELLOW}Starting Telegram Authentication Process...${NC}"
echo -e "${YELLOW}This will create a persistent session for your bot.${NC}"
echo -e "${RED}*** IMPORTANT ***${NC}"
echo -e "${YELLOW}You will be prompted for:${NC}"
echo -e "1. Your phone number"
echo -e "2. The verification code sent to your Telegram"
echo -e "3. If enabled, your 2FA password"
echo -e "${YELLOW}The session will be saved in the sessions directory${NC}"

# Function to check if session file exists
check_session_file() {
    if [ -f "sessions/telegram_bot_session.session" ]; then
        echo -e "${GREEN}Session file found!${NC}"
        return 0
    else
        echo -e "${RED}No session file found${NC}"
        return 1
    fi
}

# Start authentication process
echo -e "${YELLOW}Starting authentication container...${NC}"
docker compose run --rm -it bot python bot.py

# Check for session file
MAX_RETRIES=3
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if check_session_file; then
        # Verify file is not empty
        if [ -s "sessions/telegram_bot_session.session" ]; then
            echo -e "${GREEN}Authentication successful!${NC}"
            echo -e "${GREEN}Session file has been saved to: sessions/telegram_bot_session.session${NC}"
            echo -e "${GREEN}This file will be used for persistent authentication${NC}"
            exit 0
        else
            echo -e "${RED}Warning: Session file exists but is empty${NC}"
        fi
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo -e "${YELLOW}Session file not found or invalid. Retrying in 5 seconds... (Attempt $RETRY_COUNT of $MAX_RETRIES)${NC}"
        sleep 5
        echo -e "${YELLOW}Restarting authentication process...${NC}"
        docker compose run --rm -it bot python bot.py
    fi
done

echo -e "${RED}Failed to create valid session file after $MAX_RETRIES attempts${NC}"
echo -e "${RED}Please check your credentials and try running setup.sh again${NC}"
exit 1