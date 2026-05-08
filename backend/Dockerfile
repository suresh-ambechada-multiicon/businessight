FROM python:3.12-slim

# Python standard env vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

WORKDIR /app

# Copy uv files
COPY pyproject.toml uv.lock ./

# Add gunicorn and sync dependencies
RUN uv add gunicorn uvicorn && uv sync --frozen --no-dev

# Copy backend code
COPY . .

# Set correct permissions
RUN chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

EXPOSE 8000

# Run gunicorn with 4 workers for concurrency
CMD ["uv", "run", "gunicorn", "BusinessSight.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2"]
