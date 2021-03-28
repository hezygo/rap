from typing import Any

import pytest

from rap.client import Channel, Client, Response
from rap.common.exceptions import ChannelError, FuncNotFoundError
from rap.server import Channel as ServerChannel
from rap.server import ResponseModel, Server

pytestmark = pytest.mark.asyncio


class TestChannel:
    async def test_while_channel(self, rap_server: Server, rap_client: Client) -> None:
        msg: str = "hello!"

        @rap_client.register()
        async def async_channel(channel: Channel) -> None:
            await channel.write(msg)
            cnt: int = 0
            while await channel.loop(cnt < 3):
                cnt += 1
                await channel.write(msg)
                assert msg == await channel.read_body()
            return

        async def _async_channel(channel: ServerChannel) -> None:
            while await channel.loop():
                body: Any = await channel.read_body()
                await channel.write(body)

        rap_server.register(_async_channel, "async_channel")
        await async_channel()

    async def test_echo_body(self, rap_server: Server, rap_client: Client) -> None:
        @rap_client.register()
        async def echo_body(channel: Channel) -> None:
            msg: str = "hello!"
            cnt: int = 0
            await channel.write(msg)
            async for body in channel.iter_body():
                assert body == msg
                if cnt >= 3:
                    break
                cnt += 1
                await channel.write(body)

        async def _echo_body(channel: Channel) -> None:
            async for body in channel.iter_body():
                await channel.write(body)

        rap_server.register(_echo_body, "echo_body")
        await echo_body()

    async def test_echo_response(self, rap_server: Server, rap_client: Client) -> None:
        @rap_client.register()
        async def echo_response(channel: Channel) -> None:
            msg: str = "hello!"
            cnt: int = 0
            await channel.write(msg)
            async for response in channel.iter_response():
                # IDE cannot check
                response: Response = response  # type: ignore
                assert msg == response.body
                if cnt >= 3:
                    break
                cnt += 1
                await channel.write(response.body)

        async def _echo_response(channel: Channel) -> None:
            async for response in channel.iter_response():
                # IDE cannot check
                response: ResponseModel = response  # type: ignore
                await channel.write(response.body)

        rap_server.register(_echo_response, "echo_response")
        await echo_response()

    async def test_while_channel_close(self, rap_server: Server, rap_client: Client) -> None:
        @rap_client.register()
        async def async_channel(channel: Channel) -> None:
            await channel.write("hello")
            cnt: int = 0
            while await channel.loop(cnt < 3):
                cnt += 1
                print(await channel.read_body())
            return

        async def _async_channel(channel: Channel) -> None:
            while await channel.loop():
                body: Any = await channel.read_body()
                if body == "hello":
                    cnt: int = 0
                    await channel.close()

                    with pytest.raises(ChannelError):
                        await channel.read_body()
                    with pytest.raises(ChannelError):
                        await channel.write(f"hello {cnt}")
                else:
                    await channel.write("I don't know")

        rap_server.register(_async_channel, "async_channel")
        with pytest.raises(ChannelError) as e:
            await async_channel()

        exec_msg: str = e.value.args[0]
        assert exec_msg == "recv drop event, close channel"

    async def test_not_found_channel_func(self, rap_server: Server, rap_client: Client) -> None:
        @rap_client.register()
        async def async_channel(channel: Channel) -> None:
            await channel.write("hello")
            cnt: int = 0
            while await channel.loop(cnt < 3):
                cnt += 1
                print(await channel.read_body())
            return

        with pytest.raises(FuncNotFoundError) as e:
            await async_channel()

        exec_msg: str = e.value.args[0]
        assert exec_msg == "Not found func. name: async_channel"
