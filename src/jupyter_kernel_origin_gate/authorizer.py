"""Fail-closed authorization for a single-user Jupyter kernel endpoint.

The caller still has to pass Jupyter Server's own token authentication. This
authorizer adds an exact Origin requirement and disallows cookie/query-token
fallbacks for every kernel REST operation and the execution WebSocket.
"""

from __future__ import annotations

import hmac
import os
from urllib.parse import urlsplit

from jupyter_server.auth import Authorizer


def valid_serialized_origin(value: str) -> bool:
    """Accept a complete HTTP(S) origin, without a URL path or credentials."""
    if not value or value.strip() != value or any(c in value for c in "\r\n\\"):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.netloc == parsed.netloc.lower()
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.geturl() == value
        and (port is None or 0 < port < 65536)
    )


class KernelOriginAuthorizer(Authorizer):
    """Require explicit bearer authentication and one configured Origin.

    This is deliberately narrow: all resources other than ``kernels`` are
    denied, including terminals and sessions. The deployment is a single-user
    kernel API rather than a general Jupyter web interface.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        origin = os.environ.get("JKG_ALLOWED_ORIGIN", "")
        if not valid_serialized_origin(origin):
            raise ValueError("JKG_ALLOWED_ORIGIN must be one HTTP(S) origin")
        token = self.identity_provider.token
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("Jupyter token must be at least 32 characters")
        self.allowed_origin = origin

    def is_authorized(self, handler: object, user: object, action: str, resource: str) -> bool:
        if user is None or resource != "kernels" or action not in {"read", "write", "execute"}:
            return False
        request = handler.request  # type: ignore[attr-defined]
        headers = request.headers
        origins = headers.get_list("Origin")
        authorizations = headers.get_list("Authorization")
        if len(origins) != 1 or origins[0] != self.allowed_origin:
            return False
        if len(authorizations) != 1:
            return False
        header = authorizations[0]
        if not header.startswith("Bearer "):
            return False
        bearer = header[len("Bearer ") :]
        if not bearer or bearer.strip() != bearer or " " in bearer or "\t" in bearer:
            return False
        if "token" in request.query_arguments:
            return False
        if not hmac.compare_digest(bearer, self.identity_provider.token):
            return False
        return bool(self.identity_provider.is_token_authenticated(handler))
