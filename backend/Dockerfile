FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY backend ./backend
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
ARG INSTALL_AUDIO=false
ARG INSTALL_TRANSCRIPTION=false
RUN if [ "$INSTALL_AUDIO" = "true" ]; then uv sync --frozen --no-dev --extra audio; elif [ "$INSTALL_TRANSCRIPTION" = "true" ]; then uv sync --frozen --no-dev --extra transcription; fi
ENV PATH="/app/.venv/bin:$PATH" RN_STORAGE_DIR=/data/media
CMD ["uvicorn", "rn_live.app:app", "--host", "0.0.0.0", "--port", "8000"]
