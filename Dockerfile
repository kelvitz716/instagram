FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install gallery-dl and yt-dlp globally
RUN pip install --no-cache-dir gallery-dl yt-dlp

# Copy the rest of the application
COPY . .

# Create required directories with proper permissions
RUN mkdir -p /app/downloads /app/data /app/sessions /app/uploads /app/temp && \
    chown -R 1000:1000 /app && \
    chmod -R 775 /app && \
    chmod g+s /app/data /app/sessions  # Ensure new files inherit group permissions

# Set up runtime user
RUN groupadd -g 1000 botuser && \
    useradd -u 1000 -g botuser -s /bin/bash -m botuser && \
    chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Create a healthcheck script
COPY healthcheck.py .
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python healthcheck.py

# Environment variable for Python path
ENV PYTHONPATH=/app

# Command to run the application
CMD ["python", "bot.py"]