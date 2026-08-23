#!/usr/bin/env python3
"""driver for Icecast SOURCE Protocol, as used by Traktor and Mixxx and others?"""

import asyncio
import codecs
import io
import json
import logging
import os
import struct
import time
import urllib.parse
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config

METADATALIST: list[str] = ["artist", "title", "album", "key", "filename", "bpm"]

PLAYLIST: list[str] = ["name", "filename"]


# What we claim to be when a source client polls the status pages.
_SERVER_ID = "Icecast 2.4.4"

# A request line longer than this is not one; stop holding the bytes.
_MAX_REQUEST_LINE = 8192

# Never echoed into the log; some encoders put the source password in the query.
_SECRET_FIELDS = frozenset({"pass", "password", "auth", "token"})


def _fmt_fields(fields: dict[str, str]) -> str:
    """Render fields for a log line, withholding anything credential-shaped."""
    if not fields:
        return "(none)"
    return ", ".join(
        f"{k}={'<redacted>' if k.lower() in _SECRET_FIELDS else v!r}"
        for k, v in sorted(fields.items())
    )


class IcecastProtocol(asyncio.Protocol):
    """a terrible implementation of the Icecast SOURCE protocol"""

    def __init__(
        self,
        metadata_callback: Callable[[dict[str, str]], None] | None = None,
        metadata_reader: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.streaming: bool = False
        # bytes that arrived but do not yet form a whole page, and a packet
        # still being carried across page boundaries
        self.buffer: bytes = b""
        self.previous_page: bytes = b""
        self.warned_not_ogg: bool = False
        self.metadata_callback: Callable[[dict[str, str]], None] | None = metadata_callback
        # Reads back whatever the plugin currently holds.  A status poll arrives
        # on its own connection -- butt opened twenty in one short session -- so
        # this instance never saw the stream it is being asked about.
        self.metadata_reader: Callable[[], dict[str, str]] | None = metadata_reader

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """initial connection gives us a transport to use"""
        self.transport = transport  # type: ignore  # pylint: disable=attribute-defined-outside-init

    def data_received(self, data: bytes) -> None:
        """every time data is received, this method is called"""

        if not self.streaming:
            self.buffer += data
            request, rest = self._split_request(self.buffer)
            if request is None:
                if self._maybe_request(self.buffer):
                    return  # a request split across reads; wait for the rest
                request, rest = b"", self.buffer

            self.streaming = True
            self.buffer = b""
            self.previous_page = b""
            self.warned_not_ogg = False
            if request and self._short_request(request):
                # metadata updates and status polls each get their own
                # connection -- butt opened twenty in one short session -- so
                # answer and hang up rather than leaving a socket per poll
                self.transport.close()  # type: ignore
                return
            logging.debug("Sending initial 200")
            self.transport.write(b"HTTP/1.0 200 OK\r\n\r\n")  # type: ignore
            self.buffer = rest  # a source may flush audio behind its handshake
        else:
            request, rest = self._split_request(data)
            if request is not None:
                # a metadata update on the same connection as the audio; letting
                # it reach the page reader would wedge the buffer behind a page
                # that never completes
                self._query_parse(request)
                self.transport.write(b"HTTP/1.0 200 OK\r\n\r\n")  # type: ignore
            # TCP hands us arbitrary slices, so hold anything short of a whole
            # page until the rest turns up
            self.buffer += rest

        for packet in self._drain_packets():
            packetio = io.BytesIO(packet)
            if packet[:7] == b"\x03vorbis":
                packetio.seek(7, os.SEEK_CUR)  # jump over header name
                self._parse_vorbis_comment(packetio)
            elif packet[:8] == b"OpusTags":  # parse opus metadata:
                packetio.seek(8, os.SEEK_CUR)  # jump over header name
                self._parse_vorbis_comment(packetio)

    def _drain_packets(self) -> Iterator[bytes]:
        """Yield complete Ogg packets, holding partial pages until they finish.

        Ogg frames packets as runs of 255-byte segments closed by a shorter
        one, so the segment table is the only thing that says where a packet
        ends -- and a page can carry the tail of one packet plus the whole of
        the next.  A page can also arrive split across TCP reads, which is why
        nothing is consumed until its whole body is present.
        """
        while True:
            begin = self.buffer.find(b"OggS")
            if begin < 0:
                if len(self.buffer) > 3 and not self.warned_not_ogg:
                    # once per connection: an MP3 source produces this on every
                    # chunk, and the useful part is telling the DJ where their
                    # metadata will have to come from instead
                    self.warned_not_ogg = True
                    logging.warning(
                        "icecast: stream carries no Ogg pages (MP3?); track data can only "
                        "arrive via /admin/metadata updates from this source"
                    )
                # keep a sliver in case the capture pattern straddles reads
                self.buffer = self.buffer[-3:]
                return
            if begin:
                logging.debug("icecast: skipping %d bytes to resync on a page", begin)
                self.buffer = self.buffer[begin:]
            if len(self.buffer) < 27:
                return
            _, _, flags, _, _, _, _, segments = struct.unpack("<4sBBqIIiB", self.buffer[:27])
            body_start = 27 + segments
            if len(self.buffer) < body_start:
                return
            segsizes = self.buffer[27:body_start]
            body_end = body_start + sum(segsizes)
            if len(self.buffer) < body_end:
                return

            body = self.buffer[body_start:body_end]
            self.buffer = self.buffer[body_end:]
            if not flags & 0x01:
                # not a continuation, so anything held over was never finished
                self.previous_page = b""

            offset = 0
            for size in segsizes:
                self.previous_page += body[offset : offset + size]
                offset += size
                if size < 255:  # a short segment ends the packet
                    yield self.previous_page
                    self.previous_page = b""

    @staticmethod
    def _log_exchange(source: str, received: dict[str, str], parsed: dict[str, str]) -> None:
        """Log what a broadcaster sent and what we made of it.

        Both halves matter.  Dropping a field the DJ software displays is one
        failure; misreading one we do consume is another, and splitting
        "Artist - Title" out of a single song= is a guess that only the raw
        value can settle.
        """
        logging.debug("icecast %s received: %s", source, _fmt_fields(received))
        logging.debug("icecast %s parsed: %s", source, _fmt_fields(parsed))

    def _short_request(self, data: bytes) -> bool:
        """Answer a metadata update or status poll; True if this was one.

        These arrive on their own connection and expect a reply and a close.
        A source handshake must not come through here -- that connection has
        to stay open to carry the audio.
        """
        url = self._extract_url_from_data(data)
        if url is None:
            return False
        if url.path == "/admin/metadata":
            self._query_parse(data)
            self.transport.write(b"HTTP/1.0 200 OK\r\n\r\n")  # type: ignore
            return True
        if url.path == "/status-json.xsl":
            body = json.dumps({"icestats": self._icestats()}).encode("utf-8")
            self.transport.write(  # type: ignore
                b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode("ascii")
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            return True
        return False

    def _icestats(self) -> dict:
        """Server status in Icecast's shape, reporting only what we know.

        Zero listeners is the truth -- WNP receives a stream, it does not relay
        one -- and anything we would have to invent, such as a listenurl that
        serves nothing, is left out rather than fabricated.
        """
        stats: dict = {"server_id": _SERVER_ID, "listeners": 0, "sources": 0}
        metadata = self.metadata_reader() if self.metadata_reader else {}
        source = {field: metadata[field] for field in ("artist", "title") if metadata.get(field)}
        if not source:
            return stats

        source |= {"listeners": 0, "listener_peak": 0, "slow_listeners": 0}
        stats["sources"] = 1
        stats["source"] = source
        return stats

    def _query_parse(self, data: bytes) -> None:
        """try to parse the query"""
        # Parse the URL from the request data
        url = self._extract_url_from_data(data)
        if not url:
            return

        # Check if this is a metadata update request
        if url.path != "/admin/metadata":
            return

        query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        if query.get("mode") != ["updinfo"]:
            return

        # Extract metadata from query parameters
        metadata = self._extract_metadata_from_query(query)
        self._log_exchange("updinfo", {k: v[0] for k, v in query.items() if v}, metadata)

        # Update instance metadata and notify callback
        if not any(value for value in metadata.values()):
            # butt follows every real update with an empty song=, and every Ogg
            # connection opens with a comment block carrying only ENCODER.
            # Publishing either blanks whatever is currently playing.
            logging.debug("icecast: ignoring an update with no usable fields")
            return

        # each update describes the current track in full, so pass it on as-is:
        # merging would carry the previous track's artist onto this one, which
        # is worse than reporting none
        if self.metadata_callback:
            self.metadata_callback(metadata)

    @staticmethod
    def _split_request(data: bytes) -> tuple[bytes | None, bytes]:
        """Peel a complete HTTP request off the front, returning it and the rest.

        (None, data) means this is not a request, or not all of one yet.  Audio
        flushed behind a request in the same segment stays in the remainder
        rather than being discarded with it, and scanning only the front avoids
        mistaking audio bytes for a request line.
        """
        head, separator, rest = data.partition(b"\r\n\r\n")
        if not separator or IcecastProtocol._extract_url_from_data(head) is None:
            return None, data
        return head, rest

    @staticmethod
    def _maybe_request(data: bytes) -> bool:
        """True if data could still become an HTTP request once more arrives."""
        if b"\r\n\r\n" in data:
            return False  # headers are complete, so whatever it is, it is not one
        first = data.split(b"\r\n", 1)[0]
        if len(first) > _MAX_REQUEST_LINE:
            return False
        return first[:1].isalpha() and first.isascii()

    @staticmethod
    def _extract_url_from_data(data: bytes) -> urllib.parse.ParseResult | None:
        """Parse the target out of an HTTP request line, or None if it is not one.

        Clients vary the method and its casing, pad the line with extra spaces,
        and sometimes send an absolute-form URI.  Read the request line as the
        three tokens it is rather than matching a literal "GET ", which also
        stops the old version from mangling any payload containing that text.
        """
        line = data.split(b"\r\n", 1)[0].decode("utf-8", "replace")
        parts = line.split()
        if len(parts) != 3 or not parts[2].upper().startswith("HTTP/"):
            return None
        if "\ufffd" in line:
            # shaped like a request but not valid UTF-8, so say so -- audio
            # chunks fail the shape test above and stay quiet
            logging.warning("Failed to decode icecast query data as UTF-8")
            return None
        try:
            return urllib.parse.urlparse(parts[1])
        except ValueError as error:
            logging.warning("Failed to parse icecast query URL: %s", error)
            return None

    @staticmethod
    def _extract_metadata_from_query(query: dict[str, list[str]]) -> dict[str, str]:
        """Extract metadata from parsed query parameters"""
        metadata: dict[str, str] = {}

        # song is the fallback for clients that send nothing else -- butt only
        # ever sends this.  Splitting it on " - " is a guess, so anything
        # explicit overrides it below: Mixxx sends both and its song lags a
        # track behind the artist and title it sends alongside.
        if song_text := query.get("song", [""])[0].strip():
            if " - " in song_text:
                # first occurrence only, so "Artist - Song - Remix" keeps the
                # remix with the title
                artist, title = song_text.split(" - ", 1)
                metadata["artist"] = artist.strip()
                metadata["title"] = title.strip()
            else:
                metadata["title"] = song_text

        # tested for content, not presence: a client sending artist= with no
        # value would otherwise wipe what song= just gave us
        if artist := query.get("artist", [""])[0].strip():
            metadata["artist"] = artist
        if title := query.get("title", [""])[0].strip():
            metadata["title"] = title

        return metadata

    def _parse_vorbis_comment(  # pylint: disable=invalid-name,too-many-locals,too-many-branches
        self, fh: io.BytesIO
    ) -> None:
        """from tinytag, with slight modifications, pull out metadata"""
        comment_type_to_attr_mapping: dict[str, str] = {
            "album": "album",
            "albumartist": "albumartist",
            "title": "title",
            "artist": "artist",
            "date": "year",
            "tracknumber": "track",
            "totaltracks": "track_total",
            "discnumber": "disc",
            "totaldiscs": "disc_total",
            "genre": "genre",
            "description": "comments",
        }

        metadata: dict[str, str] = {}
        seen: dict[str, str] = {}

        # Every read is length-checked: a block cut short used to raise
        # struct.error out of here, which asyncio swallowed, so a truncated
        # comment lost the fields that did arrive as well as the ones that
        # did not.
        header = fh.read(4)
        if len(header) < 4:
            logging.warning("icecast vorbis comment ended before its vendor string")
            return
        vendor_length = struct.unpack("I", header)[0]
        fh.seek(vendor_length, os.SEEK_CUR)  # jump over vendor
        header = fh.read(4)
        if len(header) < 4:
            logging.warning("icecast vorbis comment ended before its field count")
            return
        elements = struct.unpack("I", header)[0]
        decoded = 0
        for _ in range(elements):
            raw_length = fh.read(4)
            if len(raw_length) < 4:
                break
            length = struct.unpack("I", raw_length)[0]
            chunk = fh.read(length)
            if len(chunk) < length:
                break
            try:
                keyvalpair = codecs.decode(chunk, "UTF-8")
            except UnicodeDecodeError:
                continue
            if "=" in keyvalpair:
                decoded += 1
                key, value = keyvalpair.split("=", 1)
                seen[key.lower()] = value
                if fieldname := comment_type_to_attr_mapping.get(key.lower()):
                    metadata[fieldname] = value

        if decoded != elements:
            # the block says how many fields it holds; a shortfall means the
            # packet was cut, not that the broadcaster sent little
            logging.warning(
                "icecast vorbis comment declared %d fields but only %d decoded", elements, decoded
            )
        self._log_exchange("vorbis", seen, metadata)

        # Fallback: If artist is empty but title contains " - ", try splitting the title
        artist_value = metadata.get("artist")
        if (
            (not artist_value or not artist_value.strip())
            and metadata.get("title")
            and " - " in metadata["title"]
        ):
            artist, title = metadata["title"].split(" - ", 1)
            artist = artist.strip()
            title = title.strip()
            if artist:  # Only apply the split if we get a non-empty artist
                metadata["artist"] = artist
                metadata["title"] = title

        # Update instance metadata and notify callback
        if not any(value for value in metadata.values()):
            # butt follows every real update with an empty song=, and every Ogg
            # connection opens with a comment block carrying only ENCODER.
            # Publishing either blanks whatever is currently playing.
            logging.debug("icecast: ignoring an update with no usable fields")
            return

        # each update describes the current track in full, so pass it on as-is:
        # merging would carry the previous track's artist onto this one, which
        # is worse than reporting none
        if self.metadata_callback:
            self.metadata_callback(metadata)


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """base class of input plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ) -> None:
        """no custom init"""
        super().__init__(config=config, qsettings=qsettings)
        self.displayname: str = "Icecast"
        self.server: asyncio.Server | None = None
        self.current_port: int | None = None
        self._port_config_key: str = "icecast/port"
        self._port_retry_after: float = 0.0
        self.mode: str | None = None
        self.lastmetadata: dict[str, str] = {}
        self._current_metadata: dict[str, str] = {}

    def _metadata_callback(self, metadata: dict[str, str]) -> None:
        """Callback to receive metadata from the protocol"""
        self._current_metadata = metadata

    def install(self) -> bool:
        """auto-install for Icecast"""
        return False

    #### Settings UI methods

    def defaults(self, qsettings: "QSettings") -> None:
        """(re-)set the default configuration values for this plugin"""
        qsettings.setValue("icecast/port", "8000")

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """load values from config and populate page"""
        qwidget.port_lineedit.setText(self.config.cparser.value("icecast/port"))  # type: ignore

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """take the settings page and save it"""
        self.config.cparser.setValue("icecast/port", qwidget.port_lineedit.text())  # type: ignore

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        """provide a description for the plugins page"""
        qwidget.setText(
            "Icecast is a streaming broadcast protocol."
            "  This setting should be used for butt, MIXXX, and many others."
        )

    #### Data feed methods

    async def getrandomtrack(self, playlist: str) -> None:
        return None

    #### Control methods

    async def start_port(self, port: int) -> None:
        """start the icecast server on a particular port"""
        loop = asyncio.get_running_loop()
        logging.debug("Launching Icecast on %s", port)
        try:

            def protocol_factory() -> IcecastProtocol:
                return IcecastProtocol(
                    metadata_callback=self._metadata_callback,
                    metadata_reader=lambda: self._current_metadata,
                )

            self.server = await loop.create_server(protocol_factory, "", port)
            self.current_port = port
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Failed to launch icecast: %s", error)

    async def _restart_if_port_changed(self) -> None:
        """Restart the server if the configured port has changed since start."""
        new_port: int = self.config.cparser.value(
            self._port_config_key, type=int, defaultValue=8000
        )  # type: ignore[union-attr]
        if new_port == self.current_port:
            return
        # If the last bind attempt failed, back off 30s before retrying so a
        # port held by another app that is shutting down doesn't spam the log.
        if self.server is None and time.monotonic() < self._port_retry_after:
            return
        logging.info("Icecast port changed from %s to %s, restarting", self.current_port, new_port)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        await self.start_port(new_port)
        if self.server is None:
            self._port_retry_after = time.monotonic() + 30.0

    async def getplayingtrack(self) -> TrackMetadata:
        """give back the current metadata"""
        await self._restart_if_port_changed()
        return self._current_metadata.copy()  # type: ignore

    async def start(self) -> None:
        """any initialization before actual polling starts"""
        port: int = self.config.cparser.value(self._port_config_key, type=int, defaultValue=8000)
        await self.start_port(port)

    async def stop(self) -> None:
        """stopping either the entire program or just this
        input"""
        if self.server:
            self.server.close()
