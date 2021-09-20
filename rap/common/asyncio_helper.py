import asyncio
import inspect
import sys
import time
from types import TracebackType
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type, Union


def current_task(loop: Optional[asyncio.AbstractEventLoop] = None) -> "Optional[asyncio.Task[Any]]":
    """return current task"""
    if sys.version_info >= (3, 7):
        return asyncio.current_task(loop=loop)
    else:
        return asyncio.Task.current_task(loop=loop)


def get_event_loop() -> asyncio.AbstractEventLoop:
    """get event loop in runtime"""
    if sys.version_info >= (3, 7):
        return asyncio.get_running_loop()

    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    if not loop.is_running():
        raise RuntimeError("no running event loop")
    return loop


def done_future(loop: Optional[asyncio.AbstractEventLoop] = None) -> asyncio.Future:
    """create init future, use in obj.__inti__ method"""
    future: asyncio.Future = asyncio.Future(loop=loop)
    future.set_result(True)
    return future


async def can_cancel_sleep(delay: float, *, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """Sleep method that can be cancelled"""
    await asyncio.wait_for(asyncio.Future(), delay, loop=loop)


def gen_new_param_coro(coro: Coroutine, new_param_dict: Dict[str, Any]) -> Coroutine:
    """Return a new coro according to the parameters
    >>> async def demo(a: int, b: int) -> int:
    ...     return a + b
    >>> value1: int = asyncio.run(demo(1, 3))
    >>> value2: int = asyncio.run(gen_new_param_coro(demo(1, 5), {"b": 3}))
    >>> assert value1 == value2
    """
    if not asyncio.iscoroutine(coro):
        raise TypeError("")
    qualname: str = coro.__qualname__.split(".<locals>", 1)[0].rsplit(".", 1)[0]
    func: Callable = getattr(inspect.getmodule(coro.cr_frame), qualname)
    old_param_dict: Dict[str, Any] = coro.cr_frame.f_locals
    for key, value in new_param_dict.items():
        if key not in old_param_dict:
            raise KeyError(f"Not found {key} in {old_param_dict.keys()}")
        old_param_dict[key] = value
    return func(**old_param_dict)


async def as_first_completed(
    future_list: List[Union[Coroutine, asyncio.Future]],
    not_cancel_future_list: Optional[List[Union[Coroutine, asyncio.Future]]] = None,
) -> Any:
    """Wait for multiple coroutines to process data, until one of the coroutines returns data,
    and the remaining coroutines are cancelled
    """
    not_cancel_future_list = not_cancel_future_list if not_cancel_future_list else []
    future_list.extend(not_cancel_future_list)

    (done, pending) = await asyncio.wait(future_list, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        if task not in not_cancel_future_list:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    for task in done:
        return task.result()


def del_future(future: asyncio.Future) -> None:
    """Cancel the running future and read the result"""
    if not future.cancelled():
        future.cancel()
    if future.done():
        future.result()


def safe_del_future(future: asyncio.Future) -> None:
    """Cancel the running future, read the result and not raise exc"""
    try:
        del_future(future)
    except Exception:
        pass


class Semaphore(asyncio.Semaphore):
    """Compared with the original version, an additional method `inflight` is used to obtain the current usage"""

    def __init__(self, value: int = 1, *, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.raw_value: int = value
        super(Semaphore, self).__init__(value, loop=loop)

    @property
    def inflight(self) -> int:
        value: int = self.raw_value - self._value  # type: ignore
        if value < 0:
            value = 0
        if value > self.raw_value:
            value = self.raw_value
        return value


class IgnoreDeadlineTimeoutExc(Exception):
    pass


class Deadline(object):
    """
    cancel and timeout for human
     The design is inspired by http://www.pdadians.com.cn/
    """

    def __init__(
        self, delay: float, loop: Optional[asyncio.AbstractEventLoop] = None, timeout_exc: Optional[Exception] = None
    ):
        """
        :param delay: How many seconds are before the deadline
        :param loop: Event loop
        :param timeout_exc: The exception thrown when the task is not completed at the deadline
            None: raise asyncio.Timeout
            IgnoreDeadlineTimeoutExc: not raise exc
        """
        self._delay: float = delay
        self._loop = loop or get_event_loop()
        self._timeout_exc: Exception = timeout_exc or asyncio.TimeoutError()

        self._end_timestamp: float = time.time() + self._delay
        self._end_loop_time: float = self._loop.time() + self._delay

        self._is_active: bool = False
        self._parent: Optional["Deadline"] = None
        self._child: Optional["Deadline"] = None
        self._deadline_future: asyncio.Future = asyncio.Future()
        self._loop.call_at(self._end_loop_time, self._set_deadline_future_result)

    def _set_deadline_future_result(self) -> None:
        self._deadline_future.set_result(True)

    def copy(self, timeout_exc: Optional[Exception] = None) -> "Deadline":
        """gen child Deadline"""
        if not timeout_exc:
            timeout_exc = self._timeout_exc

        deadline: "Deadline" = self.__class__(
            delay=self.end_loop_time - self._loop.time(), loop=self._loop, timeout_exc=timeout_exc
        )
        self._child = deadline
        deadline._parent = self
        return deadline

    @staticmethod
    def _timeout(future: asyncio.Future, callback_future: asyncio.Future) -> None:
        if not future.done():
            return
        if not callback_future.cancelled():
            callback_future.cancel()

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def surplus(self) -> float:
        return self._end_loop_time - self._loop.time()

    @property
    def end_timestamp(self) -> float:
        return self._end_timestamp

    @property
    def end_loop_time(self) -> float:
        return self._end_loop_time

    def __await__(self) -> Any:
        return self._deadline_future.__await__()

    async def wait_for(self, future: asyncio.Future) -> None:
        """wait future completed or deadline"""
        try:
            await asyncio.wait_for(future, self.end_loop_time - self._loop.time())
        except asyncio.TimeoutError:
            if isinstance(self._timeout_exc, IgnoreDeadlineTimeoutExc):
                return
            else:
                raise self._timeout_exc

    async def __aenter__(self) -> "Deadline":
        return self.__enter__()

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> Optional[bool]:
        return self.__exit__(exc_type, exc_val, exc_tb)

    def __enter__(self) -> "Deadline":
        if self._is_active:
            raise RuntimeError("`with` can only be called once")
        self._is_active = True
        main_task: Optional[asyncio.Task] = current_task(self._loop)
        if not main_task:
            raise RuntimeError("Can not found current task")
        self._deadline_future.add_done_callback(lambda f: self._timeout(f, main_task))  # type: ignore
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        self._is_active = False
        if self._deadline_future.done():
            if exc_type:
                if isinstance(self._timeout_exc, IgnoreDeadlineTimeoutExc):
                    return True
            raise self._timeout_exc
        else:
            self._deadline_future.set_result(True)
            return None
