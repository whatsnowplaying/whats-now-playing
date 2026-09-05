#!/usr/bin/env python3
"""Rules that hold for every input plugin, checked once rather than per plugin.

See nowplaying/inputs/CLAUDE.md for the contract these enforce.
"""

import ast
import asyncio
import pathlib
import time

import pytest  # pylint: disable=import-error

NOWPLAYING = pathlib.Path(__file__).parent.parent / "nowplaying"


def _thread_joins(node: ast.AST) -> list[int]:
    """Line numbers of no-argument .join() calls inside node.

    No arguments is what separates a thread or process join from str.join(),
    which always takes an iterable.
    """
    return [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "join"
        and not child.args
        and not child.keywords
    ]


def _async_functions_that_join() -> list[str]:
    """Every async def in nowplaying/ that joins a thread without offloading it."""
    offenders = []
    for path in sorted(NOWPLAYING.rglob("*.py")):
        if "vendor" in path.parts:
            continue
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            joins = _thread_joins(node)
            if not joins:
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "to_thread" in segment:
                continue
            rel = path.relative_to(NOWPLAYING.parent)
            offenders.append(f"{rel}:{joins[0]} in async {node.name}()")
    return offenders


def test_no_coroutine_joins_a_thread_without_offloading_it():
    """A coroutine that blocks without awaiting cannot be bounded or cancelled.

    trackpoll bounds every stop() with asyncio.wait_for, but a deadline is
    cooperative: it can only interrupt work that reaches an await. A bare
    observer.join() in an async def blocks the whole event loop instead, and
    wait_for returns late without even raising.

    asyncio.to_thread is the house fix -- it moves the join off the loop and
    creates the suspension point that makes the timeout real.
    """
    offenders = _async_functions_that_join()
    assert not offenders, "blocking join inside a coroutine:\n" + "\n".join(offenders)


@pytest.mark.asyncio
async def test_wait_for_cannot_bound_a_coroutine_that_never_awaits():
    """Why the rule above exists, rather than a style preference.

    Pins the asyncio behaviour the contract depends on, so the reasoning
    survives someone deciding the static check is pedantic.
    """

    async def blocks_without_awaiting():
        time.sleep(0.5)

    started = time.monotonic()
    await asyncio.wait_for(blocks_without_awaiting(), timeout=0.05)
    assert time.monotonic() - started >= 0.5, "the sleep was somehow interrupted"

    async def blocks_on_a_thread():
        await asyncio.to_thread(time.sleep, 0.5)

    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(blocks_on_a_thread(), timeout=0.05)
    assert time.monotonic() - started < 0.5, "offloading did not make it cancellable"
