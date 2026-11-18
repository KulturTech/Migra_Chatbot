FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ENV=dev \
    LLM_PROVIDER=mock \
    DB_PATH=/app/data/interviews.sqlite3 \
    GUIDE_PATH=/app/config/guide_de.yaml \
    SYSTEM_PROMPT_PATH=/app/prompts/system_prompt_de.md \
    STATIC_DIR=/app/static

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY prompts ./prompts
COPY static ./static

RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[llm]"

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "interviewbot.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
