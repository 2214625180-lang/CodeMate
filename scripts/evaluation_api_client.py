import argparse
import os


def add_api_token_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-token",
        default=default_api_token(),
        help=(
            "Evaluation API token. Defaults to $CODEMATE_EVALUATION_API_TOKEN "
            "or $CODEMATE_API_TOKEN."
        ),
    )


def default_api_token() -> str | None:
    return os.environ.get("CODEMATE_EVALUATION_API_TOKEN") or os.environ.get("CODEMATE_API_TOKEN")


def json_headers(api_token: str | None = None, *, content_type: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = "application/json"
    token = (api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
