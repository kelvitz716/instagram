FROM python:3.11-slim

# Install Firefox and required dependencies
RUN apt-get update && apt-get install -y \
    firefox-esr \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create directory for Firefox cookies and set proper permissions
RUN mkdir -p /app/.mozilla/firefox && \
    chown -R root:root /app/.mozilla/firefox && \
    chmod -R 755 /app/.mozilla/firefox

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create necessary directories
RUN mkdir -p downloads uploads temp

# Create a non-root user
RUN useradd -m botuser && \
    chown -R botuser:botuser /app
USER botuser

# Command to run the bot
CMD ["python", "bot.py"]
