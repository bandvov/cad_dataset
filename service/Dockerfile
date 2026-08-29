# Build context is the cad_dataset repo root (see docker-compose.yml:
# `context: ..`), specifically so this Dockerfile can COPY the canonical
# schema.py/compiler.py/validator.py from the root rather than maintaining
# a second hand-synced copy. That's the whole point of splitting this into
# a service: one place where "what does this IR mean" is defined, used by
# training (build_dataset.py, the eval callback) AND production (this
# service) alike.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# build123d/OCP needs these even for headless geometry work
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglu1-mesa \
        fontconfig \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    FONTCONFIG_PATH=/etc/fonts

RUN mkdir -p /tmp/.cache/fontconfig && fc-cache -f

WORKDIR /app

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# canonical IR interpreter -- single source of truth, see comment above
COPY schema.py compiler.py validator.py executor.py /app/cad_lib/

COPY service/app /app/app

ENV CAD_LIB_PATH=/app/cad_lib
WORKDIR /app/app

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
