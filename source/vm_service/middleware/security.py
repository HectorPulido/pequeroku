from secrets import compare_digest

from fastapi import (
    HTTPException,
    Security,
    WebSocket,
    WebSocketException,
    status,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.security.utils import get_authorization_scheme_param
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


def _valid_node_token(token: str) -> bool:
    configured = settings.AUTH_TOKEN
    return (
        bool(configured.strip())
        and configured != "N/A"
        and compare_digest(token.encode(), configured.encode())
    )


async def verify_websocket_bearer_token(websocket: WebSocket) -> None:
    scheme, token = get_authorization_scheme_param(
        websocket.headers.get("Authorization")
    )
    if scheme.lower() != "bearer" or not _valid_node_token(token):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


async def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> None:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    token = credentials.credentials
    if not _valid_node_token(token):
        raise _forbidden()
