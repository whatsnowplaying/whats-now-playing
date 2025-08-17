#!/usr/bin/env python3
"""test Images WebSocket API in webserver"""

import json

import pytest
import websockets


@pytest.mark.asyncio
async def test_images_websocket_hello(webserver_with_imagecache):
    """test Images WebSocket hello handshake"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send hello message
        hello_message = {"type": "hello", "client": "virtualdj-plugin", "version": "1.0"}
        await websocket.send(json.dumps(hello_message))

        # Receive welcome response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "welcome"
        assert data["server"] == "whats-now-playing"
        assert "version" in data  # Don't assert specific version, it changes
        assert data["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["fanart", "banner", "logo", "thumbnail"])
async def test_images_websocket_list_images_no_artist(webserver_with_imagecache, category):
    """test Images WebSocket list_images without artist"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send list_images message without artist but with category
        message = {
            "type": "list_images",
            "data_type": "artist",
            "category": category,
            "parameters": {},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "MISSING_ARTIST"
        assert "artist is required" in data["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["fanart", "banner", "logo", "thumbnail"])
async def test_images_websocket_list_images_with_artist(webserver_with_imagecache, category):
    """test Images WebSocket list_images with artist"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send list_images message with artist and category
        message = {
            "type": "list_images",
            "data_type": "artist",
            "category": category,
            "parameters": {"artist": "Test Artist"},
        }
        await websocket.send(json.dumps(message))

        # Receive image_list response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "image_list"
        assert data["data_type"] == "artist"
        assert data["category"] == category
        assert data["artist"] == "Test Artist"
        assert isinstance(data["cache_keys"], list)
        assert isinstance(data["total"], int)


@pytest.mark.asyncio
async def test_images_websocket_get_images_unsupported_data_type(webserver_with_imagecache):
    """test Images WebSocket get_images with unsupported data_type"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send get_images message with unsupported data_type
        message = {
            "type": "get_images",
            "data_type": "unsupported_type",
            "category": "fanart",
            "parameters": {},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "UNSUPPORTED_DATA_TYPE"
        assert "unsupported_type" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_get_images_missing_artist(webserver_with_imagecache):
    """test Images WebSocket get_images with missing artist parameter"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send get_images message without required artist parameter
        message = {
            "type": "get_images",
            "data_type": "artist",
            "category": "fanart",
            "parameters": {},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "MISSING_ARTIST"
        assert "artist is required" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_unknown_message_type_check_new_keys(webserver_with_imagecache):
    """test Images WebSocket with old check_new_keys message type"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send old check_new_keys message type that no longer exists
        message = {"type": "check_new_keys", "category": "fanart", "known_keys": ["key1", "key2"]}
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "UNKNOWN_MESSAGE_TYPE"
        assert "check_new_keys" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_unknown_message_type_get_image(webserver_with_imagecache):
    """test Images WebSocket with old get_image message type"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        message = {"type": "get_image", "category": "fanart", "cache_key": "some_key"}
        await websocket.send(json.dumps(message))

        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "UNKNOWN_MESSAGE_TYPE"
        assert "get_image" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_invalid_json(webserver_with_imagecache):
    """test Images WebSocket with invalid JSON"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send invalid JSON
        await websocket.send("invalid json {")

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "INVALID_JSON"
        assert "Invalid JSON" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_unknown_message_type(webserver_with_imagecache):
    """test Images WebSocket with unknown message type"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send message with unknown type
        message = {"type": "unknown_message_type", "data": "test"}
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "UNKNOWN_MESSAGE_TYPE"
        assert "Unknown message type" in data["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["fanart", "banner", "logo", "thumbnail"])
async def test_images_websocket_get_artist_images_by_category(webserver_with_imagecache, category):
    """test Images WebSocket get_images for all artist image categories"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send get_images message for specified category
        message = {
            "type": "get_images",
            "data_type": "artist",
            "category": category,
            "parameters": {"artist": "Test Artist"},
        }
        await websocket.send(json.dumps(message))

        # Receive response
        response = await websocket.recv()
        data = json.loads(response)

        # Should get no_image since no images are cached in test
        assert data["type"] == "no_image"
        assert data["data_type"] == "artist"
        assert data["category"] == category
        assert data["artist"] == "Test Artist"
        assert "message" in data


@pytest.mark.asyncio
async def test_images_websocket_get_artist_unsupported_category(webserver_with_imagecache):
    """test Images WebSocket get_images with unsupported category"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send get_images message with unsupported category
        message = {
            "type": "get_images",
            "data_type": "artist",
            "category": "unsupported_category",
            "parameters": {"artist": "Test Artist"},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "UNSUPPORTED_CATEGORY"
        assert "unsupported_category" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_get_images_missing_category(webserver_with_imagecache):
    """test Images WebSocket get_images without category parameter"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send get_images message without category parameter
        message = {
            "type": "get_images",
            "data_type": "artist",
            "parameters": {"artist": "Test Artist"},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "MISSING_CATEGORY"
        assert "category is required" in data["message"]


@pytest.mark.asyncio
async def test_images_websocket_list_images_missing_category(webserver_with_imagecache):
    """test Images WebSocket list_images without category parameter"""
    _, _, _, port = webserver_with_imagecache

    uri = f"ws://localhost:{port}/v1/images/ws"

    async with websockets.connect(uri) as websocket:
        # Send list_images message without category parameter
        message = {
            "type": "list_images",
            "data_type": "artist",
            "parameters": {"artist": "Test Artist"},
        }
        await websocket.send(json.dumps(message))

        # Receive error response
        response = await websocket.recv()
        data = json.loads(response)

        assert data["type"] == "error"
        assert data["error_code"] == "MISSING_CATEGORY"
        assert "category is required" in data["message"]
