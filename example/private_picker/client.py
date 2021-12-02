import asyncio
from typing import Set

from rap.client import Client
from rap.client.model import Request
from rap.client.processor.base import BaseProcessor
from rap.common.conn import Connection


class CheckConnProcessor(BaseProcessor):
    def __init__(self) -> None:
        self.conn_set: Set[Connection] = set()

    async def process_request(self, request: Request) -> Request:
        if request.conn and request.target.endswith("sync_sum"):
            # block event request
            self.conn_set.add(request.conn)
        return request


check_conn_processor: CheckConnProcessor = CheckConnProcessor()
client: Client = Client("example", [{"ip": "localhost", "port": "9000"}])
client.load_processor([check_conn_processor])


async def main() -> None:
    await client.start()
    async with client.endpoint.private_picker() as conn:
        for _ in range(3):
            assert 3 == (await client.transport.request("sync_sum", conn, [1, 2])).body["result"]
    await client.stop()


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        format="[%(asctime)s %(levelname)s] %(message)s", datefmt="%y-%m-%d %H:%M:%S", level=logging.DEBUG
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    assert len(check_conn_processor.conn_set) == 1