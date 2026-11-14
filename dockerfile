FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SCHOOL_DATA_DIR=/data

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsdl2-2.0-0 libsdl2-mixer-2.0-0 libasound2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 school \
    && useradd --uid 10001 --gid school --no-create-home school \
    && mkdir /data \
    && chown school:school /data

COPY requirements-lock.txt ./
RUN python -m pip install --requirement requirements-lock.txt
COPY --chown=school:school app ./app
COPY --chown=school:school alembic ./alembic
COPY --chown=school:school alembic.ini ./

USER school
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
