"""Serialize lazy runtime imports and model loading, not query inference."""
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
