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

# Copy the rest of the application
COPY . .

# Create volume mount points
RUN mkdir -p /app/downloads/sessions
VOLUME ["/app/downloads"]

# Create a healthcheck script
COPY healthcheck.py .
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python healthcheck.py

# Environment variable for Python path
ENV PYTHONPATH=/app

# Command to run the application
CMD ["python", "bot.py"]