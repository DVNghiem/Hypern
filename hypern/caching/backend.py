from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool: ...

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> int: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def set_nx(self, key: str, value: Any, ttl: Optional[int] = None) -> bool: ...

    @abstractmethod
    async def ttl(self, key: str) -> int: ...

    @abstractmethod
    async def incr(self, key: str) -> int | None: ...

    @abstractmethod
    async def clear(self) -> bool: ...
