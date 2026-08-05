from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings
from app.core.exceptions import InvalidGoogleTokenException

def verify_google_id_token(token: str) -> dict:
    """Verifies a Google Identity Services ID token: signature against
    Google's published JWKS, expiry, and that `aud` matches our own
    OAuth Client ID - without that last check, any valid Google token
    (even one issued for a completely different app) would pass.
    Returns the verified claims (sub, email, ...) on success.
    """
    if not settings.google_oauth_client_id:
        raise InvalidGoogleTokenException()
    try:
        return google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.google_oauth_client_id
        )
    except ValueError:
        raise InvalidGoogleTokenException()
