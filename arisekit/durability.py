"""Optional remote persistence barrier at the existing journal boundaries."""
from contextvars import ContextVar
from typing import Callable

checkpoint_barrier: ContextVar[Callable[[], None] | None] = ContextVar(
    "arisekit_checkpoint_barrier", default=None
)
