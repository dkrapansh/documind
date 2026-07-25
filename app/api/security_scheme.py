from fastapi.security import APIKeyHeader

# Only for Swagger's "Authorize" button and /docs requests. Real
# enforcement is AuthMiddleware; auto_error=False keeps this from
# rejecting a request on its own if no header is present.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)