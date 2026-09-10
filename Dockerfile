FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY mcp_server/requirements.txt /app/mcp_server/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp_server/requirements.txt

COPY mcp_server /app/mcp_server

CMD ["sh", "-c", "uvicorn mcp_server.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
