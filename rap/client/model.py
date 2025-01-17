from types import TracebackType
from typing import TYPE_CHECKING, Any, Optional

from rap.common.conn import Connection
from rap.common.event import Event
from rap.common.msg import BaseMsgProtocol
from rap.common.state import Context
from rap.common.types import MSG_TYPE, SERVER_BASE_MSG_TYPE
from rap.common.utils import constant

if TYPE_CHECKING:
    from rap.client.core import BaseClient


class ClientContext(Context):
    app: "BaseClient"
    conn: Connection


class Request(BaseMsgProtocol):
    def __init__(
        self,
        *,
        msg_type: int,
        target: Optional[str],
        body: Any,
        context: Context,
        header: Optional[dict] = None,
    ):
        self.msg_type: int = msg_type
        self.body: Any = body
        self.header = header or {}
        self.context: Context = context
        if target:
            self.target = target

    @property  # type: ignore
    def correlation_id(self) -> int:  # type: ignore
        return self.context.correlation_id

    @property  # type: ignore
    def target(self) -> str:  # type: ignore
        return self.header["target"]

    @target.setter
    def target(self, value: str) -> None:
        self.header["target"] = value
        self.context.target = value

    def to_msg(self) -> MSG_TYPE:
        return self.msg_type, self.correlation_id, self.header, self.body

    @classmethod
    def from_event(cls, event: Event, context: Context) -> "Request":
        request: "Request" = cls(
            msg_type=constant.CLIENT_EVENT, target=f"/_event/{event.event_name}", body=event.event_info, context=context
        )
        return request


class Response(BaseMsgProtocol):
    def __init__(
        self,
        msg_type: int,
        correlation_id: int,
        header: dict,
        body: Any,
        context: Context,
    ):
        assert correlation_id == context.correlation_id, "correlation_id error"
        self.msg_type: int = msg_type
        self.body: Any = body
        self.header = header or {}
        self.context: Context = context

        self.target: str = self.header.get("target", "")
        state_target: Optional[str] = self.context.get_value("target", None)
        if self.target and not state_target:
            self.context.target = self.target
        elif state_target:
            self.target = state_target
        else:
            raise ValueError(f"Can not found target from {self.correlation_id} request")

        self.status_code: int = self.header.get("status_code", 0)
        _, group, func_name = self.target.split("/")
        self.group: str = group
        self.func_name: str = func_name

        self.exc: Optional[Exception] = None
        self.tb: Optional[TracebackType] = None

    @property  # type: ignore
    def correlation_id(self) -> int:  # type: ignore
        return self.context.correlation_id

    @classmethod
    def from_msg(cls, *, msg: SERVER_BASE_MSG_TYPE, context: Context) -> "Response":
        return cls(*msg, context=context)
