import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.replay_cache import ReplayNonceStoreUnavailable, consume_proxy_identity_nonce

EvaluationRole = Literal["admin", "viewer"]
EvaluationTokenKind = Literal["admin", "ci", "read"]


@dataclass(frozen=True)
class EvaluationPrincipal:
    role: EvaluationRole
    login: str
    provider: str
    auth_method: Literal["open", "token"]
    token_kind: EvaluationTokenKind | None = None


@dataclass(frozen=True)
class EvaluationServiceToken:
    kind: EvaluationTokenKind
    token: str


@dataclass(frozen=True)
class ProductPrincipal:
    """Authenticated owner for the single-workspace product API.

    This is deliberately separate from MCP tenants: one owner only sees the
    repositories and Agent Runs created under the same signed identity.
    """

    owner_id: str
    login: str
    provider: str
    auth_method: Literal["local", "token"]


def get_evaluation_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_codemate_evaluation_token: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Token"),
    ] = None,
    x_codemate_evaluation_role: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Role"),
    ] = None,
    x_codemate_evaluation_user: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-User"),
    ] = None,
    x_codemate_evaluation_provider: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Provider"),
    ] = None,
    x_codemate_evaluation_identity_timestamp: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Identity-Timestamp"),
    ] = None,
    x_codemate_evaluation_identity_nonce: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Identity-Nonce"),
    ] = None,
    x_codemate_evaluation_identity_signature: Annotated[
        str | None,
        Header(alias="X-CodeMate-Evaluation-Identity-Signature"),
    ] = None,
) -> EvaluationPrincipal:
    configured_tokens = evaluation_service_tokens()
    if not configured_tokens:
        return attach_evaluation_principal(
            request,
            EvaluationPrincipal(
                role=parse_evaluation_role(x_codemate_evaluation_role) or "admin",
                login=header_identity_value(x_codemate_evaluation_user, default="local-dev"),
                provider=header_identity_value(x_codemate_evaluation_provider, default="local"),
                auth_method="open",
            ),
        )

    provided_token = bearer_token(authorization) or (x_codemate_evaluation_token or "").strip()
    matched_token = matching_evaluation_service_token(provided_token, configured_tokens)
    if matched_token:
        identity_headers_present = has_identity_headers(
            x_codemate_evaluation_role,
            x_codemate_evaluation_user,
            x_codemate_evaluation_provider,
            x_codemate_evaluation_identity_timestamp,
            x_codemate_evaluation_identity_nonce,
            x_codemate_evaluation_identity_signature,
        )
        if identity_headers_present:
            return attach_evaluation_principal(
                request,
                signed_evaluation_principal(
                    request=request,
                    expected_token=matched_token.token,
                    role=x_codemate_evaluation_role,
                    login=x_codemate_evaluation_user,
                    provider=x_codemate_evaluation_provider,
                    timestamp=x_codemate_evaluation_identity_timestamp,
                    nonce=x_codemate_evaluation_identity_nonce,
                    signature=x_codemate_evaluation_identity_signature,
                ),
            )

        if requires_signed_browser_identity(request):
            raise signed_browser_identity_required()

        return attach_evaluation_principal(
            request,
            token_principal(matched_token.kind),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Evaluation API token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_product_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_codemate_product_user: Annotated[
        str | None,
        Header(alias="X-CodeMate-Product-User"),
    ] = None,
    x_codemate_product_provider: Annotated[
        str | None,
        Header(alias="X-CodeMate-Product-Provider"),
    ] = None,
    x_codemate_product_identity_timestamp: Annotated[
        str | None,
        Header(alias="X-CodeMate-Product-Identity-Timestamp"),
    ] = None,
    x_codemate_product_identity_nonce: Annotated[
        str | None,
        Header(alias="X-CodeMate-Product-Identity-Nonce"),
    ] = None,
    x_codemate_product_identity_signature: Annotated[
        str | None,
        Header(alias="X-CodeMate-Product-Identity-Signature"),
    ] = None,
) -> ProductPrincipal:
    """Require a signed user identity when the product API is protected.

    Local development intentionally remains a one-user tool.  A configured
    token moves ownership to the signed browser/session identity, rather than
    trusting a client-controlled user header.
    """
    expected_token = (settings.product_api_token or "").strip()
    if not expected_token:
        principal = ProductPrincipal(
            owner_id="local:local-dev",
            login="local-dev",
            provider="local",
            auth_method="local",
        )
        request.state.product_principal = principal
        return principal

    provided_token = bearer_token(authorization)
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Product API token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not all(
        (
            x_codemate_product_user,
            x_codemate_product_provider,
            x_codemate_product_identity_timestamp,
            x_codemate_product_identity_nonce,
            x_codemate_product_identity_signature,
        )
    ):
        raise product_identity_required()

    login = header_identity_value(x_codemate_product_user, default="")
    provider = header_identity_value(x_codemate_product_provider, default="")
    if not login or not provider:
        raise product_identity_required()
    nonce = parse_identity_nonce(x_codemate_product_identity_nonce)
    timestamp = parse_identity_timestamp(x_codemate_product_identity_timestamp)
    now = int(time.time())
    ttl_seconds = max(1, settings.codemate_product_identity_ttl_seconds)
    if timestamp < now - ttl_seconds or timestamp > now + 60:
        raise product_identity_required()

    payload = product_identity_signature_payload(
        method=request.method,
        path_with_query=path_with_query(request),
        timestamp=str(timestamp),
        nonce=nonce,
        login=login,
        provider=provider,
    )
    if not valid_product_identity_signature(
        payload,
        x_codemate_product_identity_signature.strip(),
        expected_token,
    ):
        raise product_identity_required()
    try:
        nonce_consumed = consume_proxy_identity_nonce(f"product:{nonce}", ttl_seconds)
    except ReplayNonceStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product identity nonce store unavailable",
        ) from exc
    if not nonce_consumed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Product identity nonce already used",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = ProductPrincipal(
        owner_id=f"{provider.lower()}:{login.lower()}",
        login=login,
        provider=provider,
        auth_method="token",
    )
    request.state.product_principal = principal
    return principal


def evaluation_service_tokens() -> list[EvaluationServiceToken]:
    return [
        EvaluationServiceToken(kind=kind, token=token)
        for kind, token in (
            ("admin", (settings.evaluation_admin_token or "").strip()),
            ("ci", (settings.evaluation_ci_token or "").strip()),
            ("read", (settings.evaluation_read_token or "").strip()),
        )
        if token
    ]


def matching_evaluation_service_token(
    provided_token: str | None,
    configured_tokens: list[EvaluationServiceToken],
) -> EvaluationServiceToken | None:
    if not provided_token:
        return None
    for service_token in configured_tokens:
        if secrets.compare_digest(provided_token, service_token.token):
            return service_token
    return None


def token_principal(token_kind: EvaluationTokenKind) -> EvaluationPrincipal:
    if token_kind == "admin":
        return EvaluationPrincipal(
            role="admin",
            login="service-admin-token",
            provider="service",
            auth_method="token",
            token_kind=token_kind,
        )
    if token_kind == "ci":
        return EvaluationPrincipal(
            role="viewer",
            login="service-ci-token",
            provider="service",
            auth_method="token",
            token_kind=token_kind,
        )
    return EvaluationPrincipal(
        role="viewer",
        login="service-read-token",
        provider="service",
        auth_method="token",
        token_kind=token_kind,
    )


def attach_evaluation_principal(
    request: Request,
    principal: EvaluationPrincipal,
) -> EvaluationPrincipal:
    request.state.evaluation_principal = principal
    return principal


def signed_evaluation_principal(
    *,
    request: Request,
    expected_token: str,
    role: str | None,
    login: str | None,
    provider: str | None,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> EvaluationPrincipal:
    if not role or not login or not provider or not timestamp or not nonce or not signature:
        raise invalid_identity_signature()

    normalized_role = parse_evaluation_role(role)
    if normalized_role is None:
        raise invalid_identity_signature()

    normalized_login = header_identity_value(login, default="")
    normalized_provider = header_identity_value(provider, default="")
    if not normalized_login or not normalized_provider:
        raise invalid_identity_signature()

    normalized_nonce = parse_identity_nonce(nonce)
    timestamp_value = parse_identity_timestamp(timestamp)
    now = int(time.time())
    ttl_seconds = max(1, settings.codemate_proxy_identity_ttl_seconds)
    if timestamp_value < now - ttl_seconds or timestamp_value > now + 60:
        raise invalid_identity_signature()

    payload = identity_signature_payload(
        method=request.method,
        path_with_query=path_with_query(request),
        timestamp=str(timestamp_value),
        nonce=normalized_nonce,
        role=normalized_role,
        login=normalized_login,
        provider=normalized_provider,
    )
    if not valid_identity_signature(payload, signature.strip(), expected_token):
        raise invalid_identity_signature()

    try:
        nonce_consumed = consume_proxy_identity_nonce(normalized_nonce, ttl_seconds)
    except ReplayNonceStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation identity nonce store unavailable",
        ) from exc
    if not nonce_consumed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Evaluation identity nonce already used",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return EvaluationPrincipal(
        role=normalized_role,
        login=normalized_login,
        provider=normalized_provider,
        auth_method="token",
    )


def require_evaluation_viewer(
    principal: Annotated[EvaluationPrincipal, Depends(get_evaluation_principal)],
) -> EvaluationPrincipal:
    return principal


def require_evaluation_admin(
    principal: Annotated[EvaluationPrincipal, Depends(get_evaluation_principal)],
) -> EvaluationPrincipal:
    if principal.role == "admin":
        return principal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Evaluation admin role required",
    )


def require_evaluation_runner(
    principal: Annotated[EvaluationPrincipal, Depends(get_evaluation_principal)],
) -> EvaluationPrincipal:
    if principal.role == "admin" or principal.token_kind == "ci":
        return principal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Evaluation runner role required",
    )


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        token = value.strip()
        return token or None
    return None


def has_identity_headers(*values: str | None) -> bool:
    return any((value or "").strip() for value in values)


def requires_signed_browser_identity(request: Request) -> bool:
    if not settings.signed_browser_identity_required:
        return False
    return is_frontend_browser_proxy_request(request) or is_browser_like_request(request)


def is_frontend_browser_proxy_request(request: Request) -> bool:
    return request.headers.get("x-codemate-evaluation-client", "").strip().lower() == "browser"


def is_browser_like_request(request: Request) -> bool:
    return any(
        request.headers.get(header)
        for header in (
            "origin",
            "referer",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
        )
    )


def parse_evaluation_role(role: str | None) -> EvaluationRole | None:
    if role is None:
        return None
    normalized = role.strip().lower()
    if not normalized:
        return None
    if normalized == "admin":
        return "admin"
    if normalized == "viewer":
        return "viewer"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid evaluation role header",
    )


def parse_identity_timestamp(timestamp: str) -> int:
    try:
        return int(timestamp.strip())
    except ValueError as exc:
        raise invalid_identity_signature() from exc


def parse_identity_nonce(nonce: str) -> str:
    normalized = nonce.strip()
    if not 16 <= len(normalized) <= 128:
        raise invalid_identity_signature()
    if not all(char.isalnum() or char in "-_." for char in normalized):
        raise invalid_identity_signature()
    return normalized


def identity_signature_payload(
    *,
    method: str,
    path_with_query: str,
    timestamp: str,
    nonce: str,
    role: EvaluationRole,
    login: str,
    provider: str,
) -> str:
    return "\n".join(
        [
            "v1",
            timestamp,
            nonce,
            method.upper(),
            path_with_query,
            role,
            login,
            provider,
        ]
    )


def valid_identity_signature(payload: str, signature: str, expected_token: str) -> bool:
    return any(
        secrets.compare_digest(signature, sign_identity_payload_with_secret(payload, secret))
        for secret in proxy_identity_verification_secrets(expected_token)
    )


def sign_identity_payload(payload: str, expected_token: str, secret: str | None = None) -> str:
    return sign_identity_payload_with_secret(
        payload,
        secret or proxy_identity_current_secret(expected_token),
    )


def sign_identity_payload_with_secret(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def product_identity_signature_payload(
    *,
    method: str,
    path_with_query: str,
    timestamp: str,
    nonce: str,
    login: str,
    provider: str,
) -> str:
    return "\n".join(
        [
            "v1",
            timestamp,
            nonce,
            method.upper(),
            path_with_query,
            login,
            provider,
        ]
    )


def valid_product_identity_signature(payload: str, signature: str, expected_token: str) -> bool:
    return any(
        secrets.compare_digest(signature, sign_identity_payload_with_secret(payload, secret))
        for secret in product_identity_verification_secrets(expected_token)
    )


def product_identity_verification_secrets(expected_token: str) -> list[str]:
    current = (settings.codemate_product_identity_secret or "").strip() or expected_token
    previous = (settings.codemate_product_identity_previous_secret or "").strip()
    return [current, *([previous] if previous and previous != current else [])]


def proxy_identity_verification_secrets(expected_token: str) -> list[str]:
    secrets_to_try = [proxy_identity_current_secret(expected_token)]
    previous_secret = (settings.codemate_proxy_identity_previous_secret or "").strip()
    if previous_secret and previous_secret not in secrets_to_try:
        secrets_to_try.append(previous_secret)
    return secrets_to_try


def proxy_identity_current_secret(expected_token: str) -> str:
    return (settings.codemate_proxy_identity_secret or "").strip() or expected_token


def path_with_query(request: Request) -> str:
    if request.url.query:
        return f"{request.url.path}?{request.url.query}"
    return request.url.path


def invalid_identity_signature() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid evaluation identity signature required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def signed_browser_identity_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Signed evaluation identity required for browser requests",
        headers={"WWW-Authenticate": "Bearer"},
    )


def product_identity_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid signed product identity required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def header_identity_value(value: str | None, *, default: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return default
    if len(normalized) > 128 or any(char in normalized for char in "\r\n"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evaluation identity header is too long",
        )
    return normalized
