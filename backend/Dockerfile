FROM python:3.12-slim

# Python standard env vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/home/appuser/.cache/uv

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user with home directory
RUN addgroup --system appgroup && \
    adduser --system --group --home /home/appuser appuser && \
    mkdir -p /home/appuser/.cache/uv && \
    chown -R appuser:appgroup /home/appuser

WORKDIR /app

# Copy uv files
COPY pyproject.toml uv.lock ./

# Sync dependencies
RUN uv sync --no-dev

# Copy backend code
COPY . .
RUN rm -f .env

# Set correct permissions
RUN chown -R appuser:appgroup /app /home/appuser

# Drop root privileges
USER appuser

EXPOSE 8000

# Run gunicorn with 4 workers for concurrency
CMD ["uv", "run", "gunicorn", "BusinessSight.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2"]
