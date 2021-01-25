import time
from typing import Dict, List, Union

from rap.common.crypto import Crypto
from rap.common.exceptions import CryptoError, ParseError
from rap.common.utlis import MISS_OBJECT, Constant, gen_random_time_id
from rap.manager.redis_manager import redis_manager
from rap.server.model import RequestModel, ResponseModel
from rap.server.processor.base import BaseProcessor


class CryptoProcessor(BaseProcessor):
    def __init__(self, secret_dict, timeout: int = 60, nonce_timeout: int = 120):
        self._nonce_key: str = redis_manager.namespace + "nonce"
        self._timeout: int = timeout
        self._nonce_timeout: int = nonce_timeout

        self._key_dict: Dict[str, str] = {}
        self._crypto_dict: Dict[str, "Crypto"] = {}

        self.load_aes_key_dict(secret_dict)

    def start_event_handle(self):
        self.register(self.modify_crypto_timeout, group="crypto")
        self.register(self.modify_crypto_nonce_timeout, group="crypto")

        self.register(self.get_crypto_key_id_list, group="crypto")
        self.register(self.load_aes_key_dict, group="crypto")
        self.register(self.remove_aes, group="crypto")

    def load_aes_key_dict(self, aes_key_dict: Dict[str, str]) -> None:
        """load aes key dict. eg{'key_id': 'xxxxxxxxxxxxxxxx'}"""
        self._key_dict = aes_key_dict
        for key, value in aes_key_dict.items():
            self._key_dict[key] = value
            self._crypto_dict[value] = Crypto(value)

    def get_crypto_key_id_list(self) -> List[str]:
        """get crypto key in list"""
        return list(self._key_dict.keys())

    def get_crypto_by_key_id(self, key_id: str) -> "Union[Crypto, MISS_OBJECT]":
        key: str = self._key_dict.get(key_id, "")
        return self._crypto_dict.get(key, MISS_OBJECT)

    def get_crypto_by_key(self, key: str) -> "Union[Crypto, MISS_OBJECT]":
        return self._crypto_dict.get(key, MISS_OBJECT)

    def remove_aes(self, key: str) -> None:
        """delete aes value by key"""
        if key in self._crypto_dict:
            del self._crypto_dict[key]

    def modify_crypto_timeout(self, timeout: int) -> None:
        """modify crypto timeout param"""
        self._timeout = timeout

    def modify_crypto_nonce_timeout(self, timeout: int) -> None:
        """modify crypto nonce timeout param"""
        self._nonce_timeout = timeout

    async def process_request(self, request: RequestModel) -> RequestModel:
        """decrypt request body"""
        if type(request.body) is not bytes:
            return request
        crypto_id: str = request.header.get("crypto_id", None)
        crypto: Crypto = self.get_crypto_by_key_id(crypto_id)
        # check crypto
        if crypto == MISS_OBJECT:
            raise CryptoError("crypto id error")
        try:
            request.body = crypto.decrypt_object(request.body)
        except Exception as e:
            raise CryptoError("decrypt body error") from e

        try:
            timestamp: int = request.body.get("timestamp", 0)
            if (int(time.time()) - timestamp) > self._timeout:
                raise ParseError(extra_msg="timeout param error")
            nonce: str = request.body.get("nonce", "")
            if not nonce:
                raise ParseError(extra_msg="nonce param error")
            nonce = f"{self._nonce_key}:{nonce}"
            if await redis_manager.exists(nonce):
                raise ParseError(extra_msg="nonce param error")
            else:
                await redis_manager.redis_pool.set(nonce, 1, expire=self._nonce_timeout)
            request.body = request.body["body"]

            # set share data
            request.stats.crypto = crypto

            return request
        except Exception as e:
            raise CryptoError(str(e)) from e

    async def process_response(self, response: ResponseModel) -> ResponseModel:
        """encrypt response body"""
        if response.body and response.num != Constant.SERVER_ERROR_RESPONSE:
            try:
                crypto: Crypto = response.stats.crypto
            except AttributeError:
                return response
            response.body = {"body": response.body, "timestamp": int(time.time()), "nonce": gen_random_time_id()}
            response.body = crypto.encrypt_object(response.body)
        return response
