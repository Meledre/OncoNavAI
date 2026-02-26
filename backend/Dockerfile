FROM python:3.11-slim

WORKDIR /app
ARG PIP_INSTALL_MODE=online
COPY backend/requirements.txt /app/requirements.txt
COPY backend/vendor/wheels /opt/wheels
RUN set -eux; \
    if [ "$PIP_INSTALL_MODE" = "offline" ]; then \
      pip install --no-cache-dir --no-index --find-links=/opt/wheels -r /app/requirements.txt; \
    elif [ -n "$(ls -A /opt/wheels 2>/dev/null || true)" ]; then \
      pip install --no-cache-dir --find-links=/opt/wheels -r /app/requirements.txt; \
    else \
      pip install --no-cache-dir -r /app/requirements.txt; \
    fi

COPY backend /app/backend
COPY data /app/data
COPY docs/contracts/onco_json_pack_v1 /app/docs/contracts/onco_json_pack_v1
COPY docs/prompts /app/docs/prompts
ENV PYTHONPATH=/app

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
