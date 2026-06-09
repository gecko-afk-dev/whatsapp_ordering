# Use a lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory to /code (so it doesn't conflict with your "app" folder)
WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your code into the container
COPY . .

# Start FastAPI using Uvicorn
# 1. We changed "main:app" to "app.main:app" (assuming your main.py is inside the app folder)
# 2. We allow Render to inject its own $PORT variable dynamically
CMD sh -c "python -m app.seed_admin && python -m app.seed_trilingual && uvicorn app.main:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips '*'"