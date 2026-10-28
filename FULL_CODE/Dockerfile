# Web demo image. Build from the project root:  docker build -f FULL_CODE/Dockerfile -t voice-of-store .
# (ignore rules for this build live in FULL_CODE/Dockerfile.dockerignore; the project root may hold only the allowed top-level items)
# Run (data is NOT in the image; mount it read-only):
#   docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/data:/data:ro" \
#     -e R5_ALLOWED_HOSTS=localhost -e R5_API_KEY=change-me voice-of-store
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY FULL_CODE/requirements.txt /app/FULL_CODE/requirements.txt
RUN pip install -r /app/FULL_CODE/requirements.txt
COPY FULL_CODE /app/FULL_CODE
COPY submission /app/submission
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"
CMD ["python", "FULL_CODE/serve.py", "--host", "0.0.0.0", "--port", "8000", "--data", "/data", "--submission", "/app/submission"]
