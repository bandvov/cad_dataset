# Build context is the cad_dataset repo root (see docker-compose.yml:
# `context: ..`) so this can COPY chat_format.py directly -- the same
# module build_dataset.py uses to render training turns. That's the whole
# point: the wording the model sees here must match what it was trained
# on, not a second hand-copied implementation that can drift.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY llm-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY llm-service/app /app/app
COPY chat_format.py /app/app/chat_format.py

WORKDIR /app/app

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
