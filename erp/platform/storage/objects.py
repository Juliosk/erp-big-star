"""Binary storage port. Object keys are assigned by the owning domain."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    size: int


class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


__all__ = ["ObjectStorage", "StoredObject"]
