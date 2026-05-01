FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/data /app/.state
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e . \
    && playwright install chromium --with-deps

ENV CHD_API_HOST=0.0.0.0
ENV CHD_API_PORT=8009

EXPOSE $PORT
CMD ["chd-api"]
