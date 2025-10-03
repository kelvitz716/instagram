### Builder stage
FROM python:3.12-slim as builder

# Set working directory
WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    gallery-dl \
    yt-dlp \
    && find /usr/local -name '*.pyc' -delete \
    && find /usr/local -name '__pycache__' -delete

### Runtime stage
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 botuser \
    && useradd -u 1000 -g botuser -s /bin/bash -m botuser

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/gallery-dl /usr/local/bin/
COPY --from=builder /usr/local/bin/yt-dlp /usr/local/bin/

# Copy application code
COPY . .

# Create required directories with proper permissions
RUN mkdir -p /app/downloads /app/data /app/sessions /app/uploads /app/temp \
    && chown -R botuser:botuser /app \
    && chmod -R 775 /app \
    && chmod -R 777 /app/data \
    && chmod g+s /app/data /app/sessions

# Switch to non-root user
USER botuser

# Create a healthcheck script
COPY healthcheck.py .
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python healthcheck.py

# Set Python path and other environment variables
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

# Use tini as init process to handle signals properly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Command to run the application
CMD ["python", "bot.py"]