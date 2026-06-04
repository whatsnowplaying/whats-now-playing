"""
Unit tests for datacache RequestQueue (pending request queue).

Tests database-backed queuing, priority ordering, and request completion.
"""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

import nowplaying.datacache.pending


@pytest_asyncio.fixture
async def temp_queue(bootstrap):  # pylint: disable=unused-argument
    """Create temporary RequestQueue instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        queue = nowplaying.datacache.pending.RequestQueue(Path(temp_dir))
        await queue.initialize()
        yield queue


@pytest.mark.asyncio
async def test_queue_request(temp_queue):  # pylint: disable=redefined-outer-name
    """Test request queuing functionality"""
    # Queue a request
    success = await temp_queue.queue_request(
        provider="test_provider",
        request_key="fetch_url",
        params={"url": "https://example.com/test.jpg", "timeout": 30},
        priority=1,  # immediate
    )
    assert success is True

    # Queue duplicate request (should return False)
    success = await temp_queue.queue_request(
        provider="test_provider",
        request_key="fetch_url",
        params={"url": "https://example.com/test.jpg", "timeout": 30},
        priority=1,
    )
    assert success is False


@pytest.mark.asyncio
async def test_get_next_request_priority_order(temp_queue):  # pylint: disable=redefined-outer-name
    """Test request retrieval respects priority order"""
    # Queue batch request first
    await temp_queue.queue_request(
        provider="test",
        request_key="fetch_url",
        params={"url": "https://example.com/batch.jpg"},
        priority=2,  # batch
    )

    # Queue immediate request second
    await temp_queue.queue_request(
        provider="test",
        request_key="fetch_url",
        params={"url": "https://example.com/immediate.jpg"},
        priority=1,  # immediate
    )

    # Should get immediate priority first
    request = await temp_queue.get_next_request()
    assert request is not None
    assert request["priority"] == 1
    assert "immediate.jpg" in request["params"]["url"]

    # Should get batch priority next
    request = await temp_queue.get_next_request()
    assert request is not None
    assert request["priority"] == 2
    assert "batch.jpg" in request["params"]["url"]

    # No more requests
    request = await temp_queue.get_next_request()
    assert request is None


@pytest.mark.asyncio
async def test_complete_request(temp_queue):  # pylint: disable=redefined-outer-name
    """Test request completion"""
    # Queue and get a request
    await temp_queue.queue_request(
        provider="test",
        request_key="test_request",
        params={"test": "data"},
        priority=1,
    )

    request = await temp_queue.get_next_request()
    assert request is not None
    request_id = request["request_id"]

    # Complete successfully
    success = await temp_queue.complete_request(request_id, success=True)
    assert success is True

    # Should no longer be available
    next_request = await temp_queue.get_next_request()
    assert next_request is None
