# Backend
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Copy gunicorn config
COPY gunicorn.conf.py ./

# Create data and logs directories, then drop to an unprivileged user so the
# container never runs as root (the docker.sock mount is a privileged surface).
RUN useradd -r -M -d /app -s /usr/sbin/nologin appuser \
    && mkdir -p data logs \
    && chown -R appuser:appuser /app

# Expose port
EXPOSE 8080

# Run the application with gunicorn (production) or uvicorn (development)
USER appuser
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
