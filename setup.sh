#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging function
log() {
    local level=$1
    shift
    local message=$@
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    case "$level" in
        "INFO")  echo -e "${GREEN}[$timestamp] [INFO] $message${NC}" ;;
        "WARN")  echo -e "${YELLOW}[$timestamp] [WARN] $message${NC}" ;;
        "ERROR") echo -e "${RED}[$timestamp] [ERROR] $message${NC}" ;;
    esac
}

# Error handling
set -e
trap 'handle_error $? $LINENO $BASH_LINENO "$BASH_COMMAND" $(printf "::%s" ${FUNCNAME[@]:-})' ERR

handle_error() {
    local exit_code=$1
    local line_no=$2
    local bash_lineno=$3
    local last_command=$4
    local func_trace=$5
    log "ERROR" "Command '$last_command' failed with exit code $exit_code at line $line_no"
    log "ERROR" "Function trace: $func_trace"
}

# Check if setup has already been completed
if [ -f ".setup_complete" ]; then
    log "WARN" "Setup has already been completed!"
    log "WARN" "If you need to run setup again, delete the .setup_complete file"
    log "INFO" "=== Quick Reference Commands ==="
    log "INFO" "Start bot:      docker compose up -d"
    log "INFO" "Stop bot:       docker compose down"
    log "INFO" "View logs:      docker compose logs -f"
    log "INFO" "Restart bot:    docker compose restart"
    log "INFO" "Check status:   docker compose ps"
    exit 0
fi

log "INFO" "Starting Instagram Telegram Bot Initial Setup..."

# --- Setup Docker Compose Command for Backward Compatibility ---
DOCKER_COMPOSE_BIN=""

if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker compose"
    log "INFO" "Using 'docker compose' (v2) syntax."
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_BIN="docker-compose"
    log "INFO" "Using 'docker-compose' (v1) syntax."
else
    log "ERROR" "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    log "ERROR" "Docker is not installed. Please install Docker first."
    exit 1
fi

# Create all required directories with proper permissions
log "INFO" "Creating required directories..."
mkdir -p downloads data/db sessions uploads temp telegram logs

# Set proper permissions
chmod -R 777 sessions data
chmod 755 downloads uploads temp telegram logs

# Create database file
touch data/bot_data.db
chmod 666 data/bot_data.db

log "INFO" "Created directory structure with proper permissions:"
log "INFO" "  - downloads/: For downloaded media"
log "INFO" "  - data/: For database and persistent data (chmod 777)"
log "INFO" "  - sessions/: For Telegram session files (chmod 777)"
log "INFO" "  - uploads/: For processed files ready to upload"
log "INFO" "  - temp/: For temporary files"
log "INFO" "  - telegram/: For Telegram-related files"
log "INFO" "  - logs/: For application logs"

# Run database migration
log "INFO" "Running database migrations..."
if [ -f "migrate.py" ]; then
    python3 migrate.py || {
        log "ERROR" "Database migration failed"
        exit 1
    }
    log "INFO" "Database migrations completed"
else
    log "WARN" "No migration script found, skipping..."
fi

# Check for environment variables
log "INFO" "Checking configuration..."
if [ ! -f .env ]; then
    log "ERROR" "Error: .env file not found!"
    log "WARN" "Please create a .env file with the following variables:"
    echo "BOT_TOKEN=your_bot_token"
    echo "API_ID=your_api_id" 
    echo "API_HASH=your_api_hash"
    echo "TARGET_CHAT_ID=your_chat_id"
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
    log "ERROR" "Missing required environment variables:"
    printf '%s\n' "${MISSING_VARS[@]}"
    exit 1
fi

# Copy optimized Dockerfile and docker-compose
log "INFO" "Setting up optimized Docker configurations..."
if [ -f "Dockerfile.new" ]; then
    mv Dockerfile.new Dockerfile
    log "INFO" "Updated Dockerfile with optimizations"
fi

if [ -f "docker-compose.yml.new" ]; then
    mv docker-compose.yml.new docker-compose.yml
    log "INFO" "Updated docker-compose.yml with optimizations"
fi

# Function to check if session exists and is valid
check_session() {
    if [ -f "sessions/telegram_bot_session.session" ] && [ -s "sessions/telegram_bot_session.session" ]; then
        log "INFO" "Valid Telegram session found!"
        return 0
    else
        log "WARN" "No valid Telegram session found"
        return 1
    fi
}

# Main setup logic
log "INFO" "Building Docker containers..."
$DOCKER_COMPOSE_BIN build --pull --no-cache

if [ $? -ne 0 ]; then
    log "ERROR" "Docker build failed. Please check your Dockerfile and try again."
    exit 1
fi

# Run Telegram authentication
log "INFO" "Starting Telegram authentication process..."
chmod +x telegram_auth.sh
./telegram_auth.sh

if [ $? -ne 0 ]; then
    log "ERROR" "Telegram authentication failed. Please try again."
    exit 1
fi

# Verify session file one last time
if ! check_session; then
    log "ERROR" "Failed to verify Telegram session. Please run setup.sh again."
    exit 1
fi

# Start the bot in detached mode
log "INFO" "Starting bot in detached mode..."
$DOCKER_COMPOSE_BIN up -d

# Create setup complete marker
touch .setup_complete

log "INFO" "=== Initial setup completed successfully! ==="
log "INFO" "Bot is running with persistent Telegram sessions."

log "INFO" "=== Setup Summary ==="
log "INFO" "✅ Directories created with proper permissions"
log "INFO" "✅ Database migrations applied" 
log "INFO" "✅ Telegram authentication completed"
log "INFO" "✅ Session file saved in sessions/telegram_bot_session.session"
log "INFO" "✅ Docker containers built and started with optimizations"

log "INFO" "=== Important Information ==="
log "INFO" "Your Telegram session is saved in: sessions/telegram_bot_session.session"
log "INFO" "This file is crucial for authentication - DO NOT delete it!"
log "INFO" "The sessions directory is persistent and will preserve your login"
log "INFO" "Logs are stored in the logs/ directory"

log "INFO" "=== Daily Usage Commands ==="
log "INFO" "Start bot:      $DOCKER_COMPOSE_BIN up -d"
log "INFO" "Stop bot:       $DOCKER_COMPOSE_BIN down"
log "INFO" "View logs:      $DOCKER_COMPOSE_BIN logs -f"
log "INFO" "Restart bot:    $DOCKER_COMPOSE_BIN restart"
log "INFO" "Check status:   $DOCKER_COMPOSE_BIN ps"
log "INFO" "Check session:  Send /telegram_status to your bot"

# Show current status
log "INFO" "=== Current Status ==="
$DOCKER_COMPOSE_BIN ps

log "INFO" "Setup is complete! The bot will use the stored session for all future starts."
log "WARN" "To run setup again in the future, delete the .setup_complete file"