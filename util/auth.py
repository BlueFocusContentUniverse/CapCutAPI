"""
Authentication utilities for API endpoints.
Provides token-based authentication using environment variables.
"""

import hmac
import logging
import os
from typing import List, Optional

from flask import Request, jsonify

logger = logging.getLogger(__name__)


def get_configured_tokens() -> List[str]:
    """Read expected API tokens from environment variables.

    Supports a single token (DRAFT_API_TOKEN/API_TOKEN/AUTH_TOKEN) or
    a comma-separated list in DRAFT_API_TOKENS.

    Returns:
        List of valid tokens
    """
    tokens_env = os.getenv("DRAFT_API_TOKENS")
    single_token = (
        os.getenv("DRAFT_API_TOKEN")
        or os.getenv("API_TOKEN")
        or os.getenv("AUTH_TOKEN")
    )

    tokens = []
    if tokens_env:
        tokens.extend([t.strip() for t in tokens_env.split(",") if t.strip()])
    if single_token:
        tokens.append(single_token.strip())

    # Dedupe while preserving order
    unique: List[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token and token not in seen:
            unique.append(token)
            seen.add(token)

    return unique


def extract_token_from_request(req: Request) -> Optional[str]:
    """Extract bearer/API token from request headers or query params.

    Args:
        req: Flask request object

    Returns:
        Extracted token string or None if not found
    """
    auth_header = req.headers.get("Authorization", "")
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in ("bearer", "token"):
            return parts[1].strip()

    for header_name in ("X-API-Token", "X-Auth-Token", "X-Token"):
        header_val = req.headers.get(header_name)
        if header_val:
            return header_val.strip()

    # Optional fallback to query params for convenience
    token_param = req.args.get("api_token") or req.args.get("token")
    if token_param:
        return token_param.strip()

    return None


def verify_token(provided_token: Optional[str], expected_tokens: List[str]) -> bool:
    """Verify a provided token against expected tokens using constant-time comparison.

    Args:
        provided_token: Token provided by the client
        expected_tokens: List of valid tokens

    Returns:
        True if token is valid, False otherwise
    """
    if not provided_token:
        return False

    for expected in expected_tokens:
        if hmac.compare_digest(provided_token, expected):
            return True

    return False


def require_authentication(req: Request, api_name: str = "API"):
    """Protect API endpoints with token authentication.

    Configure one of the following env vars for valid tokens:
      - DRAFT_API_TOKEN (single token)
      - DRAFT_API_TOKENS (comma-separated list)
    Fallbacks supported: API_TOKEN, AUTH_TOKEN

    Client should send the token via:
      - Authorization: Bearer <token>
      - X-API-Token: <token> (or X-Auth-Token / X-Token)
      - ?api_token=<token> (query param, not recommended)

    Args:
        req: Flask request object
        api_name: Name of the API for logging purposes

    Returns:
        None if authentication succeeds, or a Flask JSON response with error (401)
    """
    expected_tokens = get_configured_tokens()
    if not expected_tokens:
        logger.error(f"{api_name} token not configured. Set DRAFT_API_TOKEN or DRAFT_API_TOKENS.")
        return jsonify({
            "success": False,
            "error": "Unauthorized: server missing token configuration"
        }), 401

    provided_token = extract_token_from_request(req)
    if not provided_token:
        logger.warning(f"{api_name} request missing authentication token")
        return jsonify({"success": False, "error": "Unauthorized: missing token"}), 401

    if not verify_token(provided_token, expected_tokens):
        logger.warning(f"{api_name} request with invalid token")
        return jsonify({"success": False, "error": "Unauthorized: invalid token"}), 401

    # Authentication successful
    return None

