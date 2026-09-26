FROM python:3.12-slim-bullseye

ENV PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency files first (for better caching)
COPY uv.lock pyproject.toml ./

# Install dependencies (this layer will be cached)
RUN uv sync --frozen --no-dev

# Copy application code
COPY . ./backend/

# Set Python path so backend module can be imported
ENV PYTHONPATH=/app

EXPOSE 8000

# Production server (no auto-reload). For local development with reload use:
#   uv run fastapi dev backend/main.py --host 0.0.0.0 --port 8000
CMD ["uv", "run", "fastapi", "run", "backend/main.py", "--host", "0.0.0.0", "--port", "8000"]