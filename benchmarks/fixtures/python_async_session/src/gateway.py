from dataclasses import dataclass


@dataclass(frozen=True)
class TokenResponse:
    access_token: str


class TokenGateway:
    async def fetch_token(self, refresh_token: str) -> TokenResponse:
        if not refresh_token:
            raise ValueError("refresh token is required")
        return TokenResponse(access_token=f"access:{refresh_token}")
