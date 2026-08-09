#!/usr/bin/env python3
"""/v1/events -- one-way WebSocket event stream (now-playing + request-queue deltas)

Publish-only: the server pushes typed frames ({"type", "timestamp", "payload"}), clients
never send commands over this socket.  Mutations stay on POST/DELETE /v1/requests, which
already give a real synchronous response.
"""

import asyncio
import contextlib
import logging
import re
import time
import uuid
import weakref
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

import nowplaying.db
import nowplaying.utils
import nowplaying.webserver.auth
import nowplaying.webserver.shutdown
from nowplaying.webserver.requests_handlers import RequestsHandler

if TYPE_CHECKING:
    import nowplaying.config
    from nowplaying.types import TrackMetadata

POLL_INTERVAL_SECONDS = 1.0

# Frames are only enqueued on actual change (not per poll tick), so ordinary traffic
# never gets close to this. It exists so a wedged consumer -- heartbeat is 30s, so a
# truly dead peer is usually caught well before this -- applies backpressure by
# dropping instead of growing without bound.
MAX_QUEUE_SIZE = 1000

# Matches the shape of a minted id (str(uuid.uuid4())[:8]) and any reasonable
# caller-supplied slug; short and conservative on purpose -- this only ever ends
# up in log lines and a JSON frame, not anywhere security-sensitive.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class EventsWebSocketHandler:
    """Handler for the /v1/events publish-only WebSocket"""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        stopevent: asyncio.Event,
        config_key: "web.AppKey[nowplaying.config.ConfigFile]",
        metadb_key: "web.AppKey[nowplaying.db.MetadataDB]",
        watcher_key: "web.AppKey[nowplaying.db.DBWatcher]",
        requests_watcher_key: "web.AppKey[nowplaying.db.DBWatcher]",
        events_ws_key: "web.AppKey[weakref.WeakSet[asyncio.Queue]]",
        requests_handler: RequestsHandler,
    ):
        self.stopevent = stopevent
        self.config_key = config_key
        self.metadb_key = metadb_key
        self.watcher_key = watcher_key
        self.requests_watcher_key = requests_watcher_key
        self.events_ws_key = events_ws_key
        self.requests_handler = requests_handler

    @staticmethod
    def _session_id(request: web.Request) -> str:
        """X-WNP-Client-Session lets a header-capable caller supply its own
        correlation id (the standard X-Request-ID pattern); falls back to a
        server-minted one when absent or malformed.  Never a query param -- there
        is no preceding .htm render for this endpoint to relay one from, unlike
        /wsstream et al., so a query value would be a bare, untrusted string.

        The fallback is silent rather than a rejected connection: this is a
        logging convenience, not something worth failing a connection over. And
        it must not pass an unsanitized header straight into logging.info() --
        that is a textbook log-injection vector (embed a newline, forge a fake
        log line).
        """
        candidate = request.headers.get("X-WNP-Client-Session", "")
        if _SESSION_ID_RE.match(candidate):
            return candidate
        return str(uuid.uuid4())[:8]

    @staticmethod
    def _envelope(event_type: str, payload: dict) -> dict:
        return {"type": event_type, "timestamp": int(time.time() * 1000), "payload": payload}

    @staticmethod
    def _strip_track_blobs(metadata: "TrackMetadata") -> dict:
        """currentmeta row -> wire shape: drop METADATABLOBLIST + dbid, keep coverurl.

        dbid is synthesized separately from row["id"] in _postprocess_read_last_meta
        (nowplaying/db.py) -- it is not in METADATABLOBLIST, so it needs its own
        explicit strip, same as every other consumer of read_last_meta_async()
        (_wss_do_update, websocket_lastjson_handler) already does.
        """
        stripped = dict(metadata)
        for key in nowplaying.db.METADATABLOBLIST:
            stripped.pop(key, None)
        stripped.pop("dbid", None)
        return stripped

    @staticmethod
    def diff_requests(previous: dict[int, dict], current: dict[int, dict]):
        """Pure diff, no I/O: (added, changed, removed), each {reqid: serialized_row}.

        removed carries the row's LAST-KNOWN value (from `previous`), not just the
        bare id, so a consumer gets a full record on removal too -- free, since
        `previous` already has it cached from the prior tick.

        changed is a reqid present on both sides whose serialized payload differs --
        an in-place UPDATE (respin being the one existing example: same reqid, new
        artist/title). Reported as its own frame rather than removed-then-added so a
        consumer never sees a transient empty slot for a row that never actually left
        the queue.
        """
        added = {rid: row for rid, row in current.items() if rid not in previous}
        changed = {
            rid: row for rid, row in current.items() if rid in previous and previous[rid] != row
        }
        removed = {rid: row for rid, row in previous.items() if rid not in current}
        return added, changed, removed

    async def _send_snapshot(
        self, websocket: web.WebSocketResponse, request: web.Request, session_id: str
    ) -> None:
        """connected signal, then a full track + request-queue snapshot, then a marker"""
        await websocket.send_json(self._envelope("connected", {"session_id": session_id}))
        metadata = await request.app[self.metadb_key].read_last_meta_async()
        if metadata:
            await websocket.send_json(
                self._envelope("track-update", self._strip_track_blobs(metadata))
            )
        reqs = self.requests_handler.get_requests(request.app)
        request_count = 0
        async for row in reqs.get_all_generator():
            payload = RequestsHandler.serialize_request_row(row)
            await websocket.send_json(self._envelope("request-added", payload))
            request_count += 1
        # A burst of individually-framed request-added events has no inherent
        # terminator, so a consumer can't tell "that's all of them" from "one
        # more might still be coming" without a marker -- this is that marker.
        # request_count lets it sanity-check its own tally, not just proceed.
        await websocket.send_json(
            self._envelope("snapshot-complete", {"request_count": request_count})
        )

    @staticmethod
    async def _drain_queue(websocket: web.WebSocketResponse, queue: "asyncio.Queue[dict]") -> None:
        """the only coroutine that writes to `websocket` once the connection is live"""
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)

    async def _read_until_closed(self, websocket: web.WebSocketResponse) -> None:
        """publish-only: read just to notice CLOSE/ERROR; any actual message is ignored.

        This is also how a connection notices server shutdown: stopevent is checked
        once per loop iteration, and each iteration blocks on receive() for up to 30s.
        A connection can therefore take up to that long to exit once stopevent is set,
        delaying runner.cleanup() by the same amount -- matches existing gifwords /
        guessgame behavior, so it's house-consistent, but is a real trade-off against
        forcibly closing every connection, not a free one.
        """
        while not nowplaying.webserver.shutdown.safe_stopevent_check_websocket(self.stopevent):
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=30.0)
            except TimeoutError:
                continue
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                return

    async def websocket_events_handler(self, request: web.Request):
        """GET /v1/events -- connect, get a snapshot, then receive live frames"""
        config = request.app[self.config_key]
        config.get()
        # Header preferred, ?secret= as the legacy fallback -- same contract as
        # every REST endpoint.  Not optional here the way it looked at first: the
        # browser WebSocket() constructor has no mechanism to set custom headers
        # at all (unlike fetch/XHR), so a header-only check would categorically
        # lock out any browser-rendered consumer, not just make it inconvenient.
        # Trade-off: the header exists specifically to keep the shared secret out
        # of access/proxy/browser-history logs, so a browser consumer using this
        # fallback puts it in the server's access log on every connect.
        auth_result = nowplaying.webserver.auth.check_client_auth(
            request,
            config,
            legacy_secret=request.query.get("secret", ""),
            source="Events WebSocket connect",
        )
        if auth_result == nowplaying.webserver.auth.AUTH_MISSING:
            return web.Response(status=401)
        if auth_result == nowplaying.webserver.auth.AUTH_INVALID:
            return web.Response(status=403)

        websocket = web.WebSocketResponse(heartbeat=30.0)
        await websocket.prepare(request)
        session_id = self._session_id(request)
        logging.info("Session %s: Events streamer connected from %s", session_id, request.remote)

        # Joined before the snapshot below is captured, not after: a queue only ever
        # gains frames via _broadcast's put_nowait, so joining early just means a
        # broadcast that lands mid-snapshot is queued instead of lost -- at worst one
        # duplicate frame right after the snapshot, never a client stuck showing stale
        # data until the *next* change (which is what late-joining used to risk).
        queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        request.app[self.events_ws_key].add(queue)
        reader_task: asyncio.Task | None = None
        writer_task: asyncio.Task | None = None

        try:
            # _broadcast only ever touches `queue` (see below), never `websocket`
            # directly, so _drain_queue is structurally the *only* writer to this
            # socket for its whole life -- "one writer per socket" is enforced by
            # construction, not by a comment asking callers to respect an ordering.
            await self._send_snapshot(websocket, request, session_id)
            reader_task = asyncio.create_task(self._read_until_closed(websocket))
            writer_task = asyncio.create_task(self._drain_queue(websocket, queue))
            # Exactly one of these ever finishes on its own: the reader when the
            # peer disconnects, the writer only if send_json raises.
            done, _pending = await asyncio.wait(
                {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if (error := task.exception()) is not None:
                    raise error
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Session %s: events websocket error", session_id)
        finally:
            # Cancelling this coroutine itself (aiohttp does this during
            # runner.cleanup()) raises CancelledError -- a BaseException -- straight
            # out of the `await asyncio.wait(...)` above, skipping the `except
            # Exception` block entirely and landing here with both tasks still
            # live. Doing the cancel-and-gather here instead of only on the
            # happy path means it runs on *every* exit, including that one.
            # Cancelling an already-finished task is a no-op, so this is safe to
            # do unconditionally rather than tracking which task was still running.
            for task in (reader_task, writer_task):
                if task is not None:
                    task.cancel()
            live_tasks = [task for task in (reader_task, writer_task) if task is not None]
            if live_tasks:
                await asyncio.gather(*live_tasks, return_exceptions=True)
            request.app[self.events_ws_key].discard(queue)  # stop queuing before closing below
            # An abrupt disconnect (WSMsgType.ERROR) can leave `closed` still False,
            # so this send can raise ConnectionResetError -- swallow it rather than
            # letting it escape from inside a finally and skip the disconnect log.
            with contextlib.suppress(Exception):
                if not websocket.closed:
                    await websocket.send_json(self._envelope("connection-closing", {}))
                    await websocket.close()
            logging.info("Session %s: Events streamer disconnected", session_id)
        return websocket

    def _broadcast(self, app: web.Application, frame: dict) -> None:
        # Enqueue only -- never touch a socket here. Each connection's own
        # _drain_queue is the sole writer to it; this keeps that true unconditionally
        # instead of depending on callers to sequence sends correctly.
        for queue in list(app[self.events_ws_key]):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                logging.warning(
                    "Events queue full (%d), dropping a frame for a wedged connection",
                    MAX_QUEUE_SIZE,
                )

    async def events_broadcast_task(self, app: web.Application) -> None:
        """Background task: poll both DBWatchers, broadcast only on real change"""
        logging.info("Starting events broadcast task")
        reqs = await asyncio.to_thread(self.requests_handler.get_requests, app)
        last_meta_time = app[self.watcher_key].updatetime
        last_requests_time = app[self.requests_watcher_key].updatetime
        # Baseline only -- do not announce as "added" whatever already existed when
        # the task started; that is not new.
        last_rows = {
            row["reqid"]: RequestsHandler.serialize_request_row(row)
            async for row in reqs.get_all_generator()
        }

        try:
            while not nowplaying.utils.safe_stopevent_check(self.stopevent):
                if app[self.watcher_key].updatetime > last_meta_time:
                    last_meta_time = app[self.watcher_key].updatetime
                    metadata = await app[self.metadb_key].read_last_meta_async()
                    if metadata:
                        self._broadcast(
                            app,
                            self._envelope("track-update", self._strip_track_blobs(metadata)),
                        )

                if app[self.requests_watcher_key].updatetime > last_requests_time:
                    last_requests_time = app[self.requests_watcher_key].updatetime
                    current_rows = {
                        row["reqid"]: RequestsHandler.serialize_request_row(row)
                        async for row in reqs.get_all_generator()
                    }
                    added, changed, removed = self.diff_requests(last_rows, current_rows)
                    for payload in added.values():
                        self._broadcast(app, self._envelope("request-added", payload))
                    for payload in changed.values():
                        self._broadcast(app, self._envelope("request-updated", payload))
                    for payload in removed.values():
                        self._broadcast(app, self._envelope("request-removed", payload))
                    last_rows = current_rows

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logging.info("Events broadcast task cancelled")
            raise
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Events broadcast task error")
