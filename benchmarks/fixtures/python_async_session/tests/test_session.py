import unittest

from src.gateway import TokenGateway
from src.session import refresh_session


class RefreshSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_awaits_gateway_response(self) -> None:
        access_token = await refresh_session(TokenGateway(), "refresh-123")

        self.assertEqual(access_token, "access:refresh-123")
