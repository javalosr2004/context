FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && uv pip install --system -e .

COPY src ./src
ENV PYTHONPATH=/app/src DATA_DIR=/data
EXPOSE 8000

CMD ["uvicorn", "enrichment.app:app", "--host", "0.0.0.0", "--port", "8000"]
