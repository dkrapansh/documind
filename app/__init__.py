# Single source of truth for the version string, used by the FastAPI app
# metadata (and therefore /docs and /openapi.json) and by
# GET /health/ready, so a running instance always reports the same
# version everywhere it is asked.
APP_VERSION = "0.1.0"
