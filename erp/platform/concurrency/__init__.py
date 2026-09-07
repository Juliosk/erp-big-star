"""Shared optimistic-concurrency conventions."""

from erp.platform.concurrency.optimistic import OptimisticLockError, OptimisticLockMixin

__all__ = ["OptimisticLockError", "OptimisticLockMixin"]
