from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    Security,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import settings

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="Invalid token")


async def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    token = credentials.credentials
    if token != settings.AUTH_TOKEN:
        raise _forbidden()
