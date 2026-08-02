from src.gateway import TokenGateway


async def refresh_session(gateway: TokenGateway, refresh_token: str) -> str:
    response = gateway.fetch_token(refresh_token)
    return response.access_token
