"""
Standalone dependency injection decorator for Hypern.

This module provides a standalone ``@inject`` decorator that can be used
in any module without importing the app instance, avoiding circular import
issues in large applications.

Example::

    # In services/user_routes.py
    from hypern import inject

    @inject("database")
    async def get_users(req, res, ctx, database):
        users = await database.query("SELECT * FROM users")
        res.json(users)

    # Multiple dependencies at once
    @inject("database", "config")
    async def get_settings(req, res, ctx, database, config):
        ...

    # Or stacked decorators
    @inject("config")
    @inject("database")
    async def handler(req, res, ctx, database, config):
        ...
"""

from __future__ import annotations

import functools
import inspect
from typing import Callable


def inject(*names: str) -> Callable:
    """
    Decorator to inject one or more dependencies by name from the request context.

    This is a standalone decorator that does not require a reference to the
    ``Hypern`` application instance.  Dependencies are resolved from the
    ``ctx`` (Context) object that is passed to every route handler.

    Args:
        *names: One or more dependency names to inject.

    Returns:
        A decorator that wraps the handler and passes resolved dependencies
        as additional positional arguments after ``ctx``.

    Examples:
        Single dependency::

            from hypern import inject

            @inject("database")
            async def list_users(req, res, ctx, database):
                users = await database.fetch_all()
                res.json(users)

        Multiple dependencies in one call::

            @inject("database", "config")
            async def handler(req, res, ctx, database, config):
                ...

        Stacked decorators (order matches argument order)::

            @inject("config")
            @inject("database")
            async def handler(req, res, ctx, database, config):
                ...
    """
    if not names:
        raise ValueError("inject() requires at least one dependency name")

    def decorator(handler: Callable) -> Callable:
        # Support stacking: if the handler was already wrapped by @inject,
        # unwrap to the original and merge dependency names.
        existing_names: list = getattr(handler, "_inject_names", None) or []
        original: Callable = getattr(handler, "_inject_original", handler)
        all_names: list = list(existing_names) + list(names)

        @functools.wraps(original)
        async def wrapped(req, res, ctx, *extra_args):
            deps = []
            for name in all_names:
                dep = ctx.get(name) if ctx else None
                deps.append(dep)
            all_deps = list(extra_args) + deps
            if inspect.iscoroutinefunction(original):
                await original(req, res, ctx, *all_deps)
            else:
                original(req, res, ctx, *all_deps)

        # Attach metadata so stacking and introspection work.
        wrapped._inject_names = all_names  # type: ignore[attr-defined]
        wrapped._inject_original = original  # type: ignore[attr-defined]
        return wrapped

    return decorator
