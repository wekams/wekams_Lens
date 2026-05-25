# Backend container — Wekams Lens Community Edition.
# Multi-stage build: builder installs deps, runtime is slim.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --prefix=/install "fastapi>=0.115" "uvicorn[standard]>=0.32" \
        "pydantic>=2.9" "pydantic-settings>=2.6" "httpx>=0.27" \
        "python-dotenv>=1.0" "structlog>=24.4" "sse-starlette>=2.1"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEKAMS_HOST=0.0.0.0 \
    WEKAMS_PORT=8000

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app

# Run as non-root
RUN useradd --create-home --shell /bin/bash wekams && \
    chown -R wekams:wekams /app
USER wekams

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
