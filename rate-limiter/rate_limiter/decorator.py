"""
Function decorator for enforcing rate limits on synchronous and asynchronous callables.
"""

from __future__ import annotations

import asyncio
from functools import wraps
import inspect
from typing import Any, Callable, Optional, Union

from rate_limiter.base import BaseRateLimiter, RateLimitExceeded, RateLimitResult


def rate_limit(
    limiter: BaseRateLimiter,
    key_func: Optional[Callable[..., str]] = None,
    cost: float = 1.0,
    on_breach: Optional[Callable[[str, RateLimitResult], Any]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that applies rate limiting to functions or coroutines.

    Args:
        limiter: An instance of BaseRateLimiter (e.g. TokenBucketLimiter or SlidingWindowLimiter).
        key_func: Optional callable to extract rate limit key from function arguments.
                  Defaults to the function's fully-qualified name.
        cost: Number of tokens or request units to deduct per invocation.
        on_breach: Optional callback executed when rate limit is exceeded.
                   If not provided, raises RateLimitExceeded.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        default_key = f"{fn.__module__}.{fn.__qualname__}"

        def resolve_key(*args: Any, **kwargs: Any) -> str:
            if key_func is not None:
                return str(key_func(*args, **kwargs))
            # Fallback to first argument if it's a string (e.g. client_ip or user_id)
            if args and isinstance(args[0], str):
                return args[0]
            return default_key

        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = resolve_key(*args, **kwargs)
                result = limiter.acquire(key=key, cost=cost)
                if not result.allowed:
                    if on_breach is not None:
                        return on_breach(key, result)
                    raise RateLimitExceeded(key, result)
                return await fn(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = resolve_key(*args, **kwargs)
                result = limiter.acquire(key=key, cost=cost)
                if not result.allowed:
                    if on_breach is not None:
                        return on_breach(key, result)
                    raise RateLimitExceeded(key, result)
                return fn(*args, **kwargs)
            return sync_wrapper

    return decorator
