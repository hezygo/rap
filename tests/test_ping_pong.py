import asyncio
from typing import Any

import pytest

from rap.client import Client
from rap.server import Server

pytestmark = pytest.mark.asyncio


class TestPingPong:
    async def test_ping_pong(self, rap_server: Server, rap_client: Client) -> None:
        future: asyncio.Future = asyncio.Future()
        rap_client_write = rap_client.transport.write_to_conn

        async def mock_write(*args: Any, **kwargs: Any) -> Any:
            if args[0].func_name == "pong":
                future.set_result(True)
            return await rap_client_write(*args, **kwargs)

        setattr(rap_client.transport, "write_to_conn", mock_write)
        assert True is await future
        setattr(rap_client.transport, "write_to_conn", rap_client_write)

    async def test_ping_pong_timeout(self, rap_server: Server, rap_client: Client) -> None:
        rap_client_write = rap_client.transport.write_to_conn

        async def mock_write(*args: Any, **kwargs: Any) -> Any:
            if args[0].func_name != "pong":
                return await rap_client_write(*args, **kwargs)

        setattr(rap_client.transport, "write_to_conn", mock_write)

        # until close
        for conn_model in rap_client._enpoints._conn_dict.copy().values():
            await conn_model.future

        setattr(rap_client.transport, "write_to_conn", rap_client_write)
