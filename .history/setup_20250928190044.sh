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

# Create all required directories with proper permissions
echo -e "${YELLOW}Creating required directories...${NC}"
mkdir -p downloads data/db sessions uploads temp telegram

# Set proper permissions - make session directory fully accessible
chmod -R 777 sessions data
chmod 755 downloads uploads temp telegram

# Create an empty database file if it doesn't exist
touch data/bot_data.db
chmod 666 data/bot_data.db

echo -e "${GREEN}Created directory structure with proper permissions:${NC}"
echo -e "  - downloads/: For downloaded media"
echo -e "  - data/: For database and persistent data (chmod 777)"
echo -e "  - sessions/: For Telegram session files (chmod 777)"
echo -e "  - uploads/: For processed files ready to upload"
echo -e "  - temp/: For temporary files"
echo -e "  - telegram/: For Telegram-related files"

# Function to wait for a file to appear with better error handling
wait_for_file() {
    local file="$1"
    local timeout=30  # Increased to 30 seconds
    local counter=0
    echo -e "${YELLOW}Waiting for session file: ${file}${NC}"
    
    while [ $counter -lt $timeout ]; do
        if [ -f "$file" ]; then
            echo -e "${GREEN}Session file found!${NC}"
            return 0
        fi
        sleep 1
        counter=$((counter + 1))
        echo -n "."
    done
    echo -e ""
    return 1
}

# --- IMPROVED INTERACTIVE LOGIN HANDLING ---
TELEGRAM_SESSION_FILE="sessions/telegram_bot_session.session"
SERVICE_NAME="bot"

echo -e "${YELLOW}Checking for existing Telegram session file: ${TELEGRAM_SESSION_FILE}${NC}"

if [ ! -f "$TELEGRAM_SESSION_FILE" ]; then
    echo -e "${YELLOW}Session file not found! Starting interactive login process...${NC}"
    
    echo -e "${RED}*** IMPORTANT INSTRUCTIONS ***${NC}"
    echo -e "${YELLOW}1. Enter your phone number when prompted${NC}"
    echo -e "${YELLOW}2. Enter the verification code from Telegram${NC}"
    echo -e "${YELLOW}3. Enter your 2FA password if you have one${NC}"
    echo -e "${YELLOW}4. WAIT for 'Application started' message${NC}"
    echo -e "${YELLOW}5. Press Ctrl+C AFTER you see 'Application started'${NC}"
    echo -e "${RED}*** This is CRITICAL for session file creation ***${NC}"
    echo ""
    read -p "Press Enter to continue with login process..."

    # Build the container first
    echo -e "${YELLOW}Building Docker containers...${NC}"
    $DOCKER_COMPOSE_BIN build --pull
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}Docker build failed. Please check your Dockerfile and try again.${NC}"
        exit 1
    fi

    # Create a temporary script to handle session creation with proper signal handling
    cat > /tmp/login_handler.sh << 'EOF'
#!/bin/bash
echo "Starting login process..."

# Function to handle cleanup
cleanup() {
    echo "Received interrupt signal, initiating cleanup..."
    # Give the container time to save the session
    sleep 3
    exit 0
}

# Set up signal handler
trap cleanup SIGINT SIGTERM

# Run the container
docker compose run --rm -it --no-deps bot python bot.py

# Check if session was created
if [ -f "sessions/telegram_bot_session.session" ]; then
    echo "Session file created successfully!"
    exit 0
else
    echo "Session file not found after login"
    exit 1
fi
EOF

    chmod +x /tmp/login_handler.sh
    
    # Run the login handler
    echo -e "${YELLOW}Starting interactive login (run as current user)...${NC}"
    /tmp/login_handler.sh
    
    LOGIN_EXIT_CODE=$?
    rm -f /tmp/login_handler.sh
    
    # Wait longer for session file to appear
    if wait_for_file "$TELEGRAM_SESSION_FILE"; then
        echo -e "${GREEN}Session file confirmed! Proceeding with bot startup...${NC}"
        
        # Start the full stack
        echo -e "${YELLOW}Starting bot in detached mode...${NC}"
        $DOCKER_COMPOSE_BIN up -d
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}Bot started successfully!${NC}"
        else
            echo -e "${RED}Failed to start bot in detached mode.${NC}"
            exit 1
        fi
        
    else
        echo -e "${RED}Session file was not created after login.${NC}"
        echo -e "${RED}Possible issues:${NC}"
        echo -e "${RED}  1. Login process was interrupted too early${NC}"
        echo -e "${RED}  2. Docker volume permissions issue${NC}"
        echo -e "${RED}  3. Incorrect login credentials${NC}"
        echo -e "${YELLOW}Troubleshooting steps:${NC}"
        echo -e "${YELLOW}  1. Make sure you press Ctrl+C ONLY after seeing 'Application started'${NC}"
        echo -e "${YELLOW}  2. Run: sudo chown -R \$USER:\$USER sessions/  ${NC}"
        echo -e "${YELLOW}  3. Check if session file exists: ls -la sessions/${NC}"
        exit 1
    fi

else
    echo -e "${GREEN}Session file found. Starting bot in detached mode...${NC}"
    $DOCKER_COMPOSE_BIN up --build -d
fi

# Final status
if [ $? -eq 0 ]; then
    echo -e "${GREEN}=== Setup completed successfully! ===${NC}"
    echo -e "${YELLOW}Useful commands:${NC}"
    echo -e "  View logs: $DOCKER_COMPOSE_BIN logs -f"
    echo -e "  Stop bot:  $DOCKER_COMPOSE_BIN down"
    echo -e "  Restart:   $DOCKER_COMPOSE_BIN restart"
else
    echo -e "${RED}Setup failed. Check error messages above.${NC}"
    exit 1
fi