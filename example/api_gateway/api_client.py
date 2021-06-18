import asyncio
import json
from typing import Any

from httpx import AsyncClient, Response
from websockets import connect  # type: ignore


async def example_websockets_client() -> None:
    async with connect("ws://localhost:8000/api/channel") as websocket:

        async def send_json(data: dict) -> None:
            await websocket.send(json.dumps(data))

        async def receive_json() -> dict:
            resp: dict = json.loads(await websocket.recv())
            if resp["code"] == 0:
                return resp["data"]
            else:
                raise RuntimeError(resp["msg"])

        await send_json({"group": "default", "func_name": "async_channel"})
        result: Any = await receive_json()
        if result != "accept":
            return
        cnt: int = 0
        while cnt < 3:
            await websocket.send(str(cnt))
            result = await receive_json()
            assert str(cnt) == result
            cnt += 1
        await websocket.close()


async def example_http_client() -> None:
    async with AsyncClient() as client:
        resp: Response = await client.post(
            "http://localhost:8000/api/normal",
            json={"group": "default", "func_name": "sync_sum", "func_type": "normal", "arg_list": [1, 2]},
        )
        assert 3 == resp.json()["data"]


async def main() -> None:
    await example_http_client()
    await example_websockets_client()


if __name__ == "__main__":
    asyncio.run(main())
