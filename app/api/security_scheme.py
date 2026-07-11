from fastapi.security import APIKeyHeader

# This exists purely so Swagger UI shows an "Authorize" button and attaches
# the header automatically to requests made from /docs. It does NOT perform
# any actual authentication — AuthMiddleware still does that, on every
# request, regardless of what Swagger shows. auto_error=False means FastAPI
# won't reject a request just because this dependency didn't see a header;
# real enforcement stays exactly where it already is.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)