import asyncio
import logging
import math
import sys
import time
from collections import deque
from types import TracebackType
from typing import TYPE_CHECKING, Any, Deque, Dict, Optional, Sequence, Tuple, Type
from uuid import uuid4

from rap.client.model import ClientContext, Request, Response
from rap.client.transport.channel import Channel
from rap.client.utils import get_exc_status_code_dict, raise_rap_error
from rap.common import event
from rap.common import exceptions as rap_exc
from rap.common.asyncio_helper import (
    Deadline,
    Semaphore,
    as_first_completed,
    deadline_context,
    del_future,
    done_future,
    get_event_loop,
    safe_del_future,
)
from rap.common.conn import CloseConnException, Connection
from rap.common.exceptions import IgnoreNextProcessor, RPCError
from rap.common.types import SERVER_BASE_MSG_TYPE
from rap.common.utils import constant

if TYPE_CHECKING:
    from rap.client.core import BaseClient
__all__ = ["Transport"]
logger: logging.Logger = logging.getLogger(__name__)


class Transport(object):
    """base client transport, encapsulation of custom transport protocol and proxy _conn feature"""

    _decay_time: float = 600.0

    def __init__(
        self,
        app: "BaseClient",
        host: str,
        port: int,
        weight: int,
        ssl_crt_path: Optional[str] = None,
        pack_param: Optional[dict] = None,
        unpack_param: Optional[dict] = None,
        max_inflight: Optional[int] = None,
        read_timeout: Optional[int] = None,
    ):
        self.app: "BaseClient" = app
        self._conn: Connection = Connection(
            host,
            port,
            pack_param=pack_param,
            unpack_param=unpack_param,
            ssl_crt_path=ssl_crt_path,
        )
        self._read_timeout = read_timeout or 1200

        self._max_correlation_id: int = 65535
        self._correlation_id: int = 1
        self._context_dict: Dict[int, ClientContext] = {}
        self._exc_status_code_dict: Dict[int, Type[rap_exc.BaseRapError]] = get_exc_status_code_dict()
        self._resp_future_dict: Dict[int, asyncio.Future[Tuple[Response, Optional[Exception]]]] = {}
        self._channel_queue_dict: Dict[int, asyncio.Queue[Tuple[Response, Optional[Exception]]]] = {}

        if weight > 10:
            weight = 10
        if weight < 0:
            weight = 0
        self.host: str = host
        self.port: int = port
        self.weight: int = weight
        self._ssl_crt_path: Optional[str] = ssl_crt_path
        self.score: float = 10.0

        self.listen_future: asyncio.Future = done_future()
        self.semaphore: Semaphore = Semaphore(max_inflight or 100)

        # ping
        self.inflight_load: Deque[int] = deque(maxlen=3)  # save history inflight(like Linux load)
        self.ping_future: asyncio.Future = done_future()
        self.available_level: int = 0
        self.available: bool = False
        self.last_ping_timestamp: float = time.time()
        self.rtt: float = 0.0
        self.mos: int = 5

    ######################
    # proxy _conn feature #
    ######################
    async def sleep_and_listen(self, delay: float) -> None:
        await self._conn.sleep_and_listen(delay)

    @property
    def conn_future(self) -> asyncio.Future:
        return self._conn.conn_future

    @property
    def connection_info(self) -> str:
        return self._conn.connection_info

    @property
    def peer_tuple(self) -> Tuple[str, int]:
        return self._conn.peer_tuple

    @property
    def sock_tuple(self) -> Tuple[str, int]:
        return self._conn.sock_tuple

    async def await_close(self) -> None:
        safe_del_future(self.ping_future)
        safe_del_future(self.listen_future)
        await self._conn.await_close()

    ############
    # base api #
    ############
    def is_closed(self) -> bool:
        return self._conn.is_closed() or self.listen_future.done()

    def close(self) -> None:
        safe_del_future(self.ping_future)
        del_future(self.listen_future)
        self._conn.close()

    def close_soon(self) -> None:
        get_event_loop().call_later(60, self.close)
        self.available = False

    async def connect(self) -> None:
        await self._conn.connect()
        self.available_level = 5
        self.available = True
        self.listen_future = asyncio.ensure_future(self.listen_conn())
        await self.declare()

    ##########################################
    # rap interactive protocol encapsulation #
    ##########################################
    async def process_response(self, response: Response, exc: Optional[Exception]) -> Response:
        """
        If this response is accompanied by an exception, handle the exception directly and throw it.
        """
        if not exc:
            try:
                for processor in reversed(self.app.processor_list):
                    response = await processor.process_response(response)
            except IgnoreNextProcessor:
                pass
            except Exception as e:
                exc = e
                response.exc = exc
                response.tb = sys.exc_info()[2]
        if exc:
            # why mypy not support ????
            for processor in reversed(self.app.processor_list):
                raw_response: Response = response
                try:
                    response, exc = await processor.process_exc(response, exc)  # type: ignore
                except IgnoreNextProcessor:
                    break
                except Exception as e:
                    logger.exception(
                        f"processor:{processor.__class__.__name__} handle response:{response.correlation_id} error:{e}"
                    )
                    response = raw_response
            raise exc  # type: ignore
        return response

    async def listen_conn(self) -> None:
        """listen server msg from transport"""
        logger.debug("listen:%s start", self._conn.peer_tuple)
        try:
            while not self._conn.is_closed():
                await self.response_handler()
        except (asyncio.CancelledError, CloseConnException):
            pass
        except Exception as e:
            self._conn.set_reader_exc(e)
            logger.exception(f"listen {self._conn.connection_info} error:{e}")
            if not self._conn.is_closed():
                await self._conn.await_close()

    def _broadcast_server_event(self, response: Response, exc: Exception) -> None:
        for _, future in self._resp_future_dict.items():
            future.set_result((response, exc))
        for _, queue in self._channel_queue_dict.items():
            queue.put_nowait((response, exc))

    # flake8: noqa: C901
    async def response_handler(self) -> None:
        """Distribute the response data to different consumers according to different conditions"""
        # read response msg
        try:
            response_msg: Optional[SERVER_BASE_MSG_TYPE] = await asyncio.wait_for(
                self._conn.read(), timeout=self._read_timeout
            )
            logger.debug("recv raw data: %s", response_msg)
        except asyncio.TimeoutError as e:
            logger.error(f"recv response from {self._conn.connection_info} timeout")
            raise e

        if response_msg is None:
            raise ConnectionError("Connection has been closed")
        # share state
        correlation_id: int = response_msg[1]
        context: Optional[ClientContext] = self._context_dict.get(correlation_id, None)
        if not context:
            if response_msg[0] == constant.SERVER_EVENT:
                context = ClientContext()
                context.app = self.app
                context.conn = self._conn
                context.correlation_id = correlation_id
            else:
                logger.error(f"Can not found context from {correlation_id}")
                return
        # parse response
        try:
            response: Response = Response.from_msg(msg=response_msg, context=context)
        except Exception as e:
            logger.exception(f"recv wrong response:{response_msg}, ignore error:{e}")
            return

        exc: Optional[Exception] = None
        if response.msg_type == constant.SERVER_ERROR_RESPONSE or response.status_code in self._exc_status_code_dict:
            # Generate rap standard error
            exc_class: Type["rap_exc.BaseRapError"] = self._exc_status_code_dict.get(
                response.status_code, rap_exc.BaseRapError
            )
            exc = exc_class(response.body)
            response.exc = exc
            response.tb = sys.exc_info()[2]
        # dispatch response
        if response.msg_type == constant.SERVER_EVENT:
            # server event msg handle
            if response.func_name == constant.EVENT_CLOSE_CONN:
                # server want to close...do not send data
                logger.info(f"recv close transport event, event info:{response.body}")
                self.available = False
                exc = CloseConnException(response.body)
                self._conn.set_reader_exc(exc)
                self._broadcast_server_event(response, exc)
            elif response.func_name == constant.PING_EVENT:
                request: Request = Request.from_event(event.PingEvent(""), context)
                request.msg_type = constant.SERVER_EVENT
                await asyncio.wait_for(self.write_to_conn(request), timeout=3)
            else:
                logger.error(f"recv not support event response:{response}")
        elif response.msg_type == constant.CLIENT_EVENT:
            if response.func_name in (constant.DECLARE, constant.PING_EVENT):
                if correlation_id in self._resp_future_dict:
                    self._resp_future_dict[correlation_id].set_result((response, exc))
                else:
                    logger.error(f"recv event:{response.func_name}, but not handler")
            else:
                logger.error(f"recv not support event response:{response}")
        elif response.msg_type == constant.CHANNEL_RESPONSE and correlation_id in self._channel_queue_dict:
            # put msg to channel
            self._channel_queue_dict[correlation_id].put_nowait((response, exc))
        elif response.msg_type == constant.MSG_RESPONSE and correlation_id in self._resp_future_dict:
            # set msg to future_dict's `future`
            self._resp_future_dict[correlation_id].set_result((response, exc))
        else:
            logger.error(f"Can not dispatch response: {response}, ignore")
        return

    def context(self) -> "Any":
        transport: "Transport" = self

        class TransportContext(object):
            correlation_id: int

            def __enter__(self) -> "ClientContext":
                self.correlation_id = transport._gen_correlation_id()
                context = ClientContext()
                context.app = transport.app
                context.conn = transport._conn
                context.correlation_id = self.correlation_id
                transport._context_dict[self.correlation_id] = context
                return context

            def __exit__(
                self,
                exc_type: Optional[Type[BaseException]],
                exc_val: Optional[BaseException],
                exc_tb: Optional[TracebackType],
            ) -> None:
                transport._context_dict.pop(self.correlation_id)

        return TransportContext()

    async def declare(self) -> None:
        """
        After transport is initialized, connect to the server and initialize the connection resources.
        Only include server_name and get transport id two functions, if you need to expand the function,
          you need to process the request and response of the declared life cycle through the processor
        """

        with self.context() as context:
            response: Response = await self._base_request(
                Request.from_event(event.DeclareEvent({"server_name": self.app.server_name}), context),
            )

        if (
            response.msg_type == constant.CLIENT_EVENT
            and response.func_name == constant.DECLARE
            and response.body.get("result", False)
            and "conn_id" in response.body
        ):
            self._conn.conn_id = response.body["conn_id"]
            return
        raise ConnectionError(f"transport:{self._conn} declare error")

    async def ping(self, cnt: int = 3) -> None:
        """
        Send three requests to check the response time of the client and server.
        At the same time, obtain the current quality score of the server to help the client better realize automatic
         load balancing (if the server supports this function)
        :param cnt: ping cnt
        """
        start_time: float = time.time()
        mos: int = 5
        rtt: float = 0

        async def _ping() -> None:
            nonlocal mos
            nonlocal rtt
            with self.context() as context:
                response: Response = await self._base_request(Request.from_event(event.PingEvent({}), context))
            rtt += time.time() - start_time
            mos += response.body.get("mos", 5)

        await asyncio.gather(*[_ping() for _ in range(cnt)])
        mos = mos // cnt
        rtt = rtt / cnt

        # declare
        now_time: float = time.time()
        old_last_ping_timestamp: float = self.last_ping_timestamp
        old_rtt: float = self.rtt
        old_mos: int = self.mos

        # ewma
        td: float = now_time - old_last_ping_timestamp
        w: float = math.exp(-td / self._decay_time)

        if rtt < 0:
            rtt = 0
        if old_rtt <= 0:
            w = 0

        self.rtt = old_rtt * w + rtt * (1 - w)
        self.mos = int(old_mos * w + mos * (1 - w))
        self.last_ping_timestamp = now_time
        self.score = (self.weight * mos) / self.rtt

    ####################################
    # base one by one request response #
    ####################################
    async def _base_request(self, request: Request) -> Response:
        """Send data to the server and get the response from the server.
        :param request: client request obj

        :return: return server response
        """
        try:
            response_future: asyncio.Future[Tuple[Response, Optional[Exception]]] = asyncio.Future()
            self._resp_future_dict[request.correlation_id] = response_future
            deadline: Optional[Deadline] = deadline_context.get()
            if self.app.through_deadline and deadline:
                request.header["X-rap-deadline"] = deadline.end_timestamp
            await self.write_to_conn(request)
            response, exc = await as_first_completed(
                [response_future],
                not_cancel_future_list=[self._conn.conn_future],
            )
            response = await self.process_response(response, exc)
            return response
        finally:
            pop_future: Optional[asyncio.Future] = self._resp_future_dict.pop(request.correlation_id, None)
            if pop_future:
                safe_del_future(pop_future)

    def _gen_correlation_id(self) -> int:
        correlation_id: int = self._correlation_id + 2
        # Avoid too big numbers
        self._correlation_id = correlation_id & self._max_correlation_id
        return correlation_id

    ##########################
    # base write_to_conn api #
    ##########################
    async def write_to_conn(self, request: Request) -> None:
        """gen msg_id and seng msg to transport"""
        request.header["host"] = self._conn.peer_tuple
        request.header["version"] = constant.VERSION
        request.header["user_agent"] = constant.USER_AGENT
        if not request.header.get("request_id"):
            request.header["request_id"] = str(uuid4())

        for processor in self.app.processor_list:
            await processor.process_request(request)
        await self._conn.write(request.to_msg())

    ######################
    # one by one request #
    ######################
    async def request(
        self,
        func_name: str,
        arg_param: Optional[Sequence[Any]] = None,
        call_id: Optional[int] = None,
        group: Optional[str] = None,
        header: Optional[dict] = None,
    ) -> Response:
        """msg request handle
        :param func_name: rpc func name
        :param arg_param: rpc func param
        :param call_id: server gen func next id
        :param group: func's group
        :param header: request header
        """
        group = group or constant.DEFAULT_GROUP
        call_id = call_id or -1
        arg_param = arg_param or []
        with self.context() as context:
            request: Request = Request(
                msg_type=constant.MSG_REQUEST,
                target=f"{self.app.server_name}/{group}/{func_name}",
                body={"call_id": call_id, "param": arg_param},
                context=context,
            )
            if header:
                request.header.update(header)
            response: Response = await self._base_request(request)
        if response.msg_type != constant.MSG_RESPONSE:
            raise RPCError(f"response num must:{constant.MSG_RESPONSE} not {response.msg_type}")
        if "exc" in response.body:
            exc_info: str = response.body.get("exc_info", "")
            if response.header.get("user_agent") == constant.USER_AGENT:
                raise_rap_error(response.body["exc"], exc_info)
            else:
                raise rap_exc.RpcRunTimeError(exc_info)
        return response

    def channel(self, func_name: str, group: Optional[str] = None) -> "Channel":
        """create and init channel
        :param func_name: rpc func name
        :param group: func's group
        """
        target: str = f"/{group or constant.DEFAULT_GROUP}/{func_name}"
        _context: Any = self.context()
        context: ClientContext = _context.__enter__()
        correlation_id: int = context.correlation_id
        channel: Channel = Channel(
            transport=self, target=target, channel_id=correlation_id, context=context  # type: ignore
        )
        self._channel_queue_dict[correlation_id] = channel.queue

        def _clean_channel_resource(_: asyncio.Future) -> None:
            self._channel_queue_dict.pop(correlation_id, None)
            _context.__exit__(None, None, None)

        channel.channel_conn_future.add_done_callback(_clean_channel_resource)
        return channel
