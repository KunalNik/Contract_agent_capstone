"""Lazy initialisation helper for expensive module-level singletons."""
import threading
from typing import Any, Callable


class LazyProxy:
    """Defers building an object until an attribute is first used.

    Lets modules keep exposing names like ``graph`` or ``embedding`` without
    connecting to Neo4j or Gemini at import time, so the app (and tests) can
    start even when those services are unavailable.
    """

    def __init__(self, factory: Callable[[], Any], name: str = "resource"):
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_instance", None)
        object.__setattr__(self, "_lock", threading.Lock())

    def _get(self) -> Any:
        instance = object.__getattribute__(self, "_instance")
        if instance is None:
            with object.__getattribute__(self, "_lock"):
                instance = object.__getattribute__(self, "_instance")
                if instance is None:
                    instance = object.__getattribute__(self, "_factory")()
                    object.__setattr__(self, "_instance", instance)
        return instance

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get(), item)

    def __setattr__(self, key: str, value: Any) -> None:
        setattr(self._get(), key, value)

    def reset(self) -> None:
        """Drop the cached instance (used by tests and reconnect logic)."""
        object.__setattr__(self, "_instance", None)

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_name")
        built = object.__getattribute__(self, "_instance") is not None
        return f"<LazyProxy {name} {'initialised' if built else 'pending'}>"
