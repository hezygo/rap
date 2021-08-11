import time
from dataclasses import MISSING
from typing import Any, Dict, Optional, Tuple

from .utils import get_event_loop


class Cache(object):
    def __init__(self, interval: Optional[float] = None) -> None:
        self._dict: Dict[Any, Tuple[float, Any]] = {}
        self._interval: float = interval or 10.0

    def _add(self, key: Any, expire: float, value: Any = MISSING) -> None:
        self._dict[key] = (time.time() + expire, value)

    def update_expire(self, key: Any, expire: float) -> bool:
        if key not in self._dict:
            return False
        _, value = self._dict[key]
        self._dict[key] = (expire, value)
        return True

    def get_and_update_expire(self, key: Any, expire: float, default: Any = MISSING) -> Any:
        if key not in self:
            raise KeyError(key)
        _, value = self._dict[key]
        self._dict[key] = (expire, value)
        if value is MISSING:
            if default is MISSING:
                raise KeyError(key)
            return default
        return value

    def get(self, key: Any, default: Any = MISSING) -> Any:
        if key not in self:
            raise KeyError(key)
        expire, value = self._dict[key]
        if value is MISSING:
            if default is MISSING:
                raise KeyError(key)
            return default
        return value

    def add(self, key: Any, expire: float, value: Any = MISSING) -> None:
        self._add(key, expire, value)
        if get_event_loop().is_running():
            self._auto_remove()
            setattr(self, self.add.__name__, self._add)

    def __contains__(self, key: Any) -> bool:
        if key not in self._dict:
            return False

        expire, value = self._dict[key]
        if expire < time.time():
            del self._dict[key]
            return False
        else:
            return True

    def _auto_remove(self) -> None:
        for key in list(self._dict.keys()):
            if key in self:
                # NOTE: After Python 3.7, the dict is ordered.
                # Since the inserted data is related to time, the dict here is also ordered by time
                break

        get_event_loop().call_later(self._interval, self._auto_remove)