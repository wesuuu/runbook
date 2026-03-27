from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.security import decode_access_token, decode_offline_token

PUBLIC_PATHS = {
    "/auth/login",
    "/auth/register",
    "/auth/verify-email",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
}

VERIFICATION_ALLOWED_PATHS = {
    "/auth/resend-verification",
    "/auth/me",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Decodes JWT on every protected request and stashes the payload
    on ``request.state.token_payload``.

    Public paths are skipped.  Offline tokens (scope="offline") are
    decoded and stashed as ``request.state.offline_payload`` — the
    revocation check remains in the downstream dependency.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        token = self._extract_bearer(request)
        if token is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        # Try offline token first (has "scope": "offline")
        offline_payload = decode_offline_token(token)
        if offline_payload is not None:
            request.state.offline_payload = offline_payload
            request.state.token_payload = None
            return await call_next(request)

        # Normal access token
        payload = decode_access_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Verification scope gating — temp tokens only allow resend + me
        if payload.scope == "verification":
            if request.url.path not in VERIFICATION_ALLOWED_PATHS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Email not verified"},
                )

        # Unverified regular token gating
        if not payload.email_verified and payload.scope is None:
            if request.url.path not in VERIFICATION_ALLOWED_PATHS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Email not verified"},
                )

        request.state.token_payload = payload
        request.state.offline_payload = None
        return await call_next(request)

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            return auth[7:]
        return None
