import asyncio
import logging
from typing import Any, Dict, Optional

from rap.client.endpoint.base import BaseEndpoint, SelectConnEnum
from rap.common.coordinator import ETCD_EVENT_VALUE_DICT_TYPE, EtcdClient


class EtcdEndpoint(BaseEndpoint):
    def __init__(
        self,
        server_name: str,
        timeout: int = 9,
        ssl_crt_path: Optional[str] = None,
        select_conn_method: SelectConnEnum = SelectConnEnum.random,
        # etcd client param
        etcd_host: str = "localhost",
        etcd_port: int = 2379,
        etcd_ttl: int = 60,
        etcd_namespace: str = "rap",
        etcd_cert_path: Optional[str] = None,
        etcd_key_path: Optional[str] = None,
        etcd_ca_path: Optional[str] = None,
    ):
        self.etcd_client: EtcdClient = EtcdClient(
            host=etcd_host,
            port=etcd_port,
            ttl=etcd_ttl,
            namespace=etcd_namespace,
            cert_path=etcd_cert_path,
            key_path=etcd_key_path,
            ca_path=etcd_ca_path,
        )
        super().__init__(server_name, timeout, ssl_crt_path, select_conn_method)

    async def start(self) -> None:
        if not self.is_close:
            raise ConnectionError(f"{self.__class__.__name__} is running")
        async for item in self.etcd_client.discovery(self.server_name):
            await self.create(item["host"], item["port"], 10)

        wait_start_future: asyncio.Future = asyncio.Future()
        if not self._conn_dict:
            logging.warning(f"Can not found conn info from etcd, wait {self.server_name} server start")
        else:
            wait_start_future.set_result(True)

        _cache_dict: Dict[str, Any] = {}

        async def create(etcd_value_dict: ETCD_EVENT_VALUE_DICT_TYPE) -> None:
            _cache_dict[etcd_value_dict["key"]] = etcd_value_dict["value"]
            await self.create(etcd_value_dict["value"]["host"], etcd_value_dict["value"]["port"], 10)
            if not wait_start_future.done():
                wait_start_future.set_result(True)

        async def destroy(etcd_value_dict: ETCD_EVENT_VALUE_DICT_TYPE) -> None:
            conn_dict: dict = _cache_dict.get(etcd_value_dict["key"], {})
            if not conn_dict:
                raise KeyError(f"Can not found key:{etcd_value_dict['key']}")
            await self.destroy(conn_dict["host"], conn_dict["port"])
            if not self._conn_dict:
                logging.warning(f"client not conn")

        asyncio.ensure_future(self.etcd_client.watch(self.server_name, [create], [destroy]))
        await wait_start_future