"""Platform-specific utilities."""

import asyncio
import platform
import selectors


def is_windows() -> bool:
    return platform.system() == "Windows"


def run_async(coro, *, debug=False):
    """Run an async coroutine with a compatible event loop on all platforms.

    On Windows the default ``ProactorEventLoop`` is incompatible with psycopg's
    async implementation.  This helper switches to a ``SelectorEventLoop`` on
    Windows while keeping the default on Unix.
    """
    if is_windows():
        return asyncio.run(
            coro,
            debug=debug,
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    return asyncio.run(coro, debug=debug)
