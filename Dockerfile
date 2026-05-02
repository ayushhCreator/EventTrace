FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer — only rebuilds when pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . --no-build-isolation || true

# Copy source after deps (so source changes don't bust the pip cache layer)
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Install Playwright Chromium (needed by monitor + scheduler services)
RUN playwright install chromium --with-deps

COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

# Runtime env — overridable via Railway service variables
ENV CHD_API_HOST=0.0.0.0
ENV CHD_API_PORT=8009
ENV PYTHONUNBUFFERED=1

EXPOSE 8009

CMD ["scripts/start-api.sh"]
