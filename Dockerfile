FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GIT_PYTHON_REFRESH=quiet

RUN chmod +x scripts/start.sh

# Migrations no longer gate the server. See scripts/start.sh for why the
# previous `alembic upgrade head && uvicorn ...` turned every database
# problem into a total outage with no way to diagnose it.
CMD ["./scripts/start.sh"]
