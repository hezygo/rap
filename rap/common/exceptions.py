from typing import Optional


class BaseRapError(Exception):
    status_code: int = 500
    message: str = "Error"

    def __init__(self, message: Optional[str] = None, extra_msg: Optional[str] = None):
        if message is None:
            message = self.message
        if extra_msg:
            message += f". {extra_msg}"
        super().__init__(message)


class AuthError(BaseRapError):
    status_code: int = 401
    message: str = "Auth Error"


class FuncNotFoundError(BaseRapError):
    status_code: int = 402
    message: str = "Not found func"


class TooManyRequest(BaseRapError):
    status_code: int = 403
    message: str = "This user has exceeded an allotted request count. Try again later."


class RPCError(BaseRapError):
    status_code: int = 500
    message: str = "Rpc error"


class LifeCycleError(BaseRapError):
    status_code: int = 501
    message: str = "Life cycle error"


class ParseError(BaseRapError):
    status_code: int = 502
    message: str = "Parse error"


class ProtocolError(BaseRapError):
    status_code: int = 503
    message: str = "Invalid protocol"


class RegisteredError(BaseRapError):
    status_code: int = 504
    message: str = "Register Error"


class RpcRunTimeError(BaseRapError):
    status_code: int = 505
    message: str = "Rpc run time error"


class ServerError(BaseRapError):
    status_code: int = 506
    message: str = "Server error"


class CryptoError(BaseRapError):
    status_code: int = 507
    message: str = "crypto error"


class ChannelError(BaseRapError):
    status_code: int = 508
    message: str = "Channel Error"


class IgnoreNextProcessor(Exception):
    pass
