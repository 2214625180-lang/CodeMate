from src.gateway import TokenGateway
from src.session import refresh_session


async def rotate_access_token(refresh_token: str) -> dict[str, str]:
    access_token = await refresh_session(TokenGateway(), refresh_token)
    return {"access_token": access_token}
