FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Dependency caching layer ---
# Copy only pyproject.toml first; stub app/__init__.py so hatchling can build
# the wheel and install all deps without the full source (better layer cache).
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# --- Application source (separate layer — doesn't bust dep cache) ---
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Migrations run via Railway releaseCommand; start server directly
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 75 --backlog 2048
