FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libssl-dev curl git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Agent source
COPY agents/ .

# Deployments dir (mounted at runtime)
RUN mkdir -p deployments

ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

EXPOSE 9003 9004

CMD ["python", "agent.py"]
