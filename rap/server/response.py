import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Tuple, Optional

from rap.conn.connection import ServerConnection
from rap.common.exceptions import BaseRapError, ServerError
from rap.common.types import BASE_RESPONSE_TYPE
from rap.common.utlis import Constant, parse_error


@dataclass()
class ResponseModel(object):
    response_num: int = Constant.MSG_RESPONSE
    msg_id: int = -1
    header: dict = field(default_factory=dict)
    result: Optional[dict] = None
    exception: Optional[BaseRapError] = None
    event: Optional[Tuple[str, Any]] = None


async def response(conn: ServerConnection, resp: ResponseModel, timeout: Optional[int] = None):
    logging.debug(f"resp:{resp}")
    if resp.exception is not None:
        error_response: Optional[Tuple[str, str]] = parse_error(resp.exception)
        resp.header["status_code"] = resp.exception.status_code
        response_msg: BASE_RESPONSE_TYPE = (Constant.SERVER_ERROR_RESPONSE, resp.msg_id, resp.header, error_response)
    elif resp.result is not None:
        response_msg: BASE_RESPONSE_TYPE = (resp.response_num, resp.msg_id, resp.header, resp.result)
    elif resp.event is not None:
        response_msg: BASE_RESPONSE_TYPE = (Constant.SERVER_EVENT, resp.msg_id, resp.header, resp.event)
    else:
        exception: BaseRapError = ServerError("not response data")
        error_response: Optional[Tuple[str, str]] = parse_error(exception)
        resp.header["status_code"] = exception.status_code
        response_msg: BASE_RESPONSE_TYPE = (Constant.SERVER_ERROR_RESPONSE, resp.msg_id, resp.header, error_response)

    try:
        await conn.write(response_msg, timeout)
    except asyncio.TimeoutError:
        logging.error(f"response to {conn.peer} timeout. result:{resp.result}, error:{resp.exception}")
    except Exception as e:
        logging.error(f"response to {conn.peer} error: {e}. result:{resp.result}, error:{resp.exception}")
