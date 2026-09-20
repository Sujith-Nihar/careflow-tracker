# The evaluation worker. Nothing else runs from this image.
#
# It carries the backend package (domain types, derivation, structured logging),
# the evaluation runner's replay path, and the scenario files, because a worker
# job is a replay run recorded through the evidence API. It deliberately does not
# carry Playwright or a browser: voice runs are driven from a developer machine,
# never from this container, so a browser here would be 400MB of attack surface
# for a code path that can never execute.
#
# Build from the repository root:
#   docker build -t careflow/worker:latest .
# Run locally against the demo queue:
#   docker run --rm --env-file .env careflow/worker:latest
FROM python:3.12-slim

# Fail fast and log straight through, so CloudWatch sees a line when it is written
# rather than when a buffer fills.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so editing a scenario file does not reinstall the world.
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app/__init__.py backend/app/__init__.py
RUN pip install --no-cache-dir -e backend && pip install --no-cache-dir "boto3>=1.35"

# Only what the worker actually imports.
COPY backend/ backend/
COPY worker/ worker/
COPY evals/runner/ evals/runner/
COPY evals/scenarios/ evals/scenarios/
COPY evals/__init__.py evals/__init__.py
COPY scripts/_env.py scripts/_env.py

# Least privilege inside the container too: nothing here needs to write to disk or
# to be root. Settings arrive as environment variables injected from SSM; no .env
# file is copied in and none is needed.
RUN useradd --create-home --uid 10001 worker && chown -R worker:worker /app
USER worker

CMD ["python", "-m", "worker.main"]
