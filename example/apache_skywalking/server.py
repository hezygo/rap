import asyncio

from skywalking import agent, config

from rap.server import Server, UserChannel
from rap.server.plugin.processor.apache_skywalking import SkywalkingProcessor

config.init(service_name="rap server service", log_reporter_active=True)


async def echo_body(channel: UserChannel) -> None:
    cnt: int = 0
    async for body in channel.iter_body():
        await asyncio.sleep(1)
        cnt += 1
        print(cnt, body)
        if cnt > 2:
            break
        await channel.write(f"pong! {cnt}")


async def async_sum(a: int, b: int) -> int:
    await asyncio.sleep(0.01)  # mock io time
    return a + b


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        format="[%(asctime)s %(levelname)s] %(message)s", datefmt="%y-%m-%d %H:%M:%S", level=logging.DEBUG
    )
    agent.start()
    loop = asyncio.new_event_loop()
    rpc_server: Server = Server("example")
    rpc_server.load_processor([SkywalkingProcessor()])
    rpc_server.register(async_sum)
    rpc_server.register(echo_body)
    loop.run_until_complete(rpc_server.run_forever())
    agent.stop()
