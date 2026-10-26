"""Serialize lazy runtime imports and model loading, not query inference."""
import ctypes
import ctypes.util
import gc
import sys
from collections.abc import Callable
from functools import wraps
from threading import RLock

_load_lock = RLock()


def serialized_model_load[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def load(*args: P.args, **kwargs: P.kwargs) -> T:
        with _load_lock:
            return function(*args, **kwargs)
    return load


def release_unused_memory() -> None:
    """Return freed heap pages to the OS after a model load or unload.

    glibc keeps freed tensor buffers in its arenas, so an fp32 load that is then
    quantized, or a model that was dropped, otherwise stays in RSS for good.
    """
    gc.collect()
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        libc.malloc_trim(0)
    except (OSError, AttributeError):
        # Not glibc (for example musl); nothing to trim.
        pass
