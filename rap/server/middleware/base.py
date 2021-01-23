from abc import ABC
from typing import Any, Callable, Coroutine, List, Union, TYPE_CHECKING

from rap.common.conn import ServerConnection
from rap.common.middleware import BaseMiddleware as _BaseMiddleware
from rap.server.model import RequestModel

if TYPE_CHECKING:
    from rap.server import Server


class BaseMiddleware(_BaseMiddleware, ABC):
    app: "Server"

    def register(self, func: Callable, is_root: bool = True, group: str = "middleware"):
        self.app.register(func, group=group)

    def start_event_handle(self):
        pass

    def stop_event_handle(self):
        pass


class BaseConnMiddleware(BaseMiddleware):
    """
    Currently, the conn can be processed in the conn middleware only after the server establishes the link
    """

    async def __call__(self, *args, **kwargs):
        return await self.dispatch(*args)

    def register(self, func: Callable, is_root: bool = True, group: str = "conn_middleware"):
        super().register(func, is_root, group)

    async def call_next(self, value: Any):
        pass

    async def dispatch(self, conn: ServerConnection):
        raise NotImplementedError


class BaseMsgMiddleware(BaseMiddleware):
    def register(self, func: Callable, is_root: bool = True, group: str = "msg_middleware"):
        super().register(func, is_root, group)

    async def dispatch(self, request: RequestModel, call_id: int, func: Callable, param: str) -> Union[dict, Exception]:
        raise NotImplementedError
