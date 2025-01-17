import inspect
import random
import string
import time
from enum import Enum, auto
from typing import Any, Callable, Dict, Sequence, Tuple

from rap.common.types import is_type

__all__ = [
    "constant",
    "EventEnum",
    "RapFunc",
    "check_func_type",
    "gen_random_time_id",
    "parse_error",
    "param_handle",
    "response_num_dict",
]


_STR_LD = string.ascii_letters + string.digits


class _Constant(object):

    __initialized: bool = False

    def __init__(self) -> None:
        self.__initialized = True
        if self.__initialized:
            raise RuntimeError("Can not support initialized")

    VERSION: str = "0.1"  # protocol version
    USER_AGENT: str = "Python3-0.5.3"
    SOCKET_RECV_SIZE: int = 1024 ** 1

    # msg type
    SERVER_ERROR_RESPONSE: int = 100
    MSG_REQUEST: int = 101
    MSG_RESPONSE: int = 201
    CHANNEL_REQUEST: int = 102
    CHANNEL_RESPONSE: int = 202
    CLIENT_EVENT: int = 103
    SERVER_EVENT: int = 203

    # event func name
    EVENT_CLOSE_CONN: str = "event_close_conn"
    PING_EVENT: str = "ping"

    # life cycle
    DECLARE: str = "declare"
    MSG: str = "MSG"
    DROP: str = "drop"

    # request type
    CHANNEL_TYPE: str = "channel"
    NORMAL_TYPE: str = "normal"

    DEFAULT_GROUP: str = "default"

    def __setattr__(self, key: Any, value: Any) -> None:
        if self.__initialized:
            raise RuntimeError("Can not set new value in runtime")


constant: _Constant = _Constant()


class _SubRapFunc(object):
    def __init__(self, func: Callable, raw_func: Callable, *args: Any, **kwargs: Any):
        self.func: Callable = func
        self.raw_func: Callable = raw_func

        self._arg_param: Sequence[Any] = args
        self._kwargs_param: Dict[str, Any] = kwargs

        self.__name__ = self.func.__name__

    def __await__(self) -> Any:
        """support await coro(x, x)"""
        return self.func(*self._arg_param, **self._kwargs_param).__await__()

    def __aiter__(self) -> Any:
        """support async for i in coro(x, x)"""
        return self.func(*self._arg_param, **self._kwargs_param).__aiter__()


class RapFunc(object):
    """
    Normally, a coroutine is created after calling the async function.
     In rap, hope that when the async function is called, it will still return the normal function,
     and the coroutine will not be generated until the await is called.
    """

    def __init__(self, func: Callable, raw_func: Callable):
        self.func: Callable = func
        self.raw_func: Callable = raw_func

        self.__name__ = self.func.__name__

    def __call__(self, *args: Any, **kwargs: Any) -> "_SubRapFunc":
        if inspect.iscoroutinefunction(self.func):
            return self.func(*args, **kwargs)
        return _SubRapFunc(self.func, self.raw_func, *args, **kwargs)


def gen_random_time_id(length: int = 8, time_length: int = 10) -> str:
    """Simply generate ordered id"""
    return str(int(time.time()))[-time_length:] + "".join(random.choice(_STR_LD) for _ in range(length))


def parse_error(exception: Exception) -> Tuple[str, str]:
    """parse python exc and return exc name and info"""
    return type(exception).__name__, str(exception)


response_num_dict: Dict[int, int] = {
    constant.MSG_REQUEST: constant.MSG_RESPONSE,
    constant.CHANNEL_REQUEST: constant.CHANNEL_RESPONSE,
    constant.CLIENT_EVENT: constant.CLIENT_EVENT,
    constant.SERVER_EVENT: constant.SERVER_EVENT,
}


def check_func_type(func_sig: inspect.Signature, param_list: Sequence[Any], default_param_dict: Dict[str, Any]) -> None:
    """Check whether the input parameter type is consistent with the function parameter type"""
    for index, parameter_tuple in enumerate(func_sig.parameters.items()):
        name, parameter = parameter_tuple
        if parameter.default is parameter.empty:
            value: Any = param_list[index]
        else:
            value = default_param_dict.get(name, parameter.default)
        if not is_type(type(value), parameter.annotation):
            raise TypeError(f"{value} type must: {parameter.annotation}")


def param_handle(
    func_sig: inspect.Signature, param_list: Sequence[Any], default_param_dict: Dict[str, Any]
) -> Tuple[Any, ...]:
    """Check whether the parameter is legal and whether the parameter type is correct"""
    new_param_list: Tuple[Any, ...] = func_sig.bind(*param_list, **default_param_dict).args
    check_func_type(func_sig, param_list, default_param_dict)
    return new_param_list


class EventEnum(Enum):
    before_start = auto()
    after_start = auto()
    before_end = auto()
    after_end = auto()
