# Backend image: API, general worker, and scheduler all run from this image
# with different start commands.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /srv/app

# Locked dependencies first so application edits do not invalidate the layer.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations

RUN pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 astra \
    && chown -R astra:astra /srv/app

USER astra

EXPOSE 8000

# Railway supplies $PORT; the shell form expands it. Locally it defaults to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
