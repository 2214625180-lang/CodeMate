import os
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query
from fastapi.responses import RedirectResponse
import uvicorn

app = FastAPI(title="CodeMate Mock Identity Provider")


@app.get("/authorize")
def authorize(
    redirect_uri: str,
    state: str,
    code_challenge: str = Query(min_length=20),
):
    query = urlencode({"code": "e2e-code", "state": state})
    return RedirectResponse(f"{redirect_uri}?{query}")


@app.post("/token")
def token(
    grant_type: str = Form(),
    code: str | None = Form(default=None),
    refresh_token: str | None = Form(default=None),
    code_verifier: str | None = Form(default=None),
):
    if grant_type == "authorization_code" and (code != "e2e-code" or not code_verifier):
        return {"error": "invalid_grant"}
    if grant_type == "refresh_token" and refresh_token != "e2e-refresh":
        return {"error": "invalid_grant"}
    return {
        "access_token": "e2e-access",
        "refresh_token": "e2e-refresh",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "mcp.read",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("MOCK_IDP_PORT", "8766")))
