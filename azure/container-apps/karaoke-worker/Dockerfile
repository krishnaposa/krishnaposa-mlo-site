# Build from repository root, e.g.:
#   az acr build -g RESOURCE_GROUP -r ACR_NAME -f azure/container-apps/karaoke-worker/Dockerfile .
FROM python:3.10-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY azure/virtualmachine/karaoke-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY azure/virtualmachine/karaoke-agent/local_worker.py .

ENV PYTHONUNBUFFERED=1
ENV OUTPUT_BASE=/tmp/karaoke-out
ENV FFMPEG_DIR=

RUN mkdir -p /tmp/karaoke-out

CMD ["python", "-u", "local_worker.py"]
