# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EVENTS_FILE=/app/data/events.json \
    TIMEZONE=Asia/Jakarta

WORKDIR /app

RUN groupadd --system --gid 10001 botminton \
    && useradd --system --uid 10001 --gid botminton --create-home botminton \
    && mkdir -p /app/data \
    && chown -R botminton:botminton /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY main.py ./
COPY botminton ./botminton

RUN chown -R botminton:botminton /app

USER botminton

VOLUME ["/app/data"]

STOPSIGNAL SIGINT

CMD ["python", "main.py"]
