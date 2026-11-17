"""Incremental JSON-array reader.

A SODA page is an array of objects. This reader yields one object at a time
and stops when the caller stops, or when the byte cap is hit. It never
appends the chunks into one statewide document.
"""

from __future__ import annotations

import json


MAX_STREAM_BYTES = 2 * 1024 * 1024


def _as_text(chunk):
    if isinstance(chunk, str):
        return chunk
    return bytes(chunk).decode("utf-8", "replace")


def _error_message(buf):
    try:
        value, _index = json.JSONDecoder().raw_decode(buf.lstrip("\ufeff"))
    except json.JSONDecodeError:
        return "Open data returned an error."
    if isinstance(value, dict):
        text = value.get("message") or value.get("error") or "Open data returned an error."
        return " ".join(str(text).split())[:300]
    return "Open data returned an error."


class ArrayReader:
    """Yield dicts from a JSON array streamed as chunks.

    ``truncated`` is set when ``max_bytes`` is reached. The unread tail of
    ``chunks`` stays unread. A JSON object (a SODA error) sets ``error`` and
    yields nothing.
    """

    def __init__(self, chunks, max_bytes=MAX_STREAM_BYTES):
        self.chunks = iter(chunks or [])
        self.max_bytes = max(1, int(max_bytes))
        self.total = 0
        self.buf = ""
        self.started = False
        self.done = False
        self.truncated = False
        self.error = ""
        self._decoder = json.JSONDecoder()

    def __iter__(self):
        return self

    def __next__(self):
        while not self.done:
            while True:
                if self.buf.startswith("\ufeff"):
                    self.buf = self.buf[1:]
                self.buf = self.buf.lstrip()
                if not self.buf:
                    break
                if not self.started:
                    if self.buf[0] == "{":
                        self.error = _error_message(self.buf)
                        self.done = True
                        raise StopIteration
                    if self.buf[0] != "[":
                        self.error = "Open data did not return a JSON array."
                        self.done = True
                        raise StopIteration
                    self.started = True
                    self.buf = self.buf[1:]
                    continue
                if self.buf[0] == "]":
                    self.done = True
                    raise StopIteration
                if self.buf[0] == ",":
                    self.buf = self.buf[1:]
                    continue
                try:
                    value, index = self._decoder.raw_decode(self.buf)
                except json.JSONDecodeError:
                    break
                self.buf = self.buf[index:]
                if isinstance(value, dict):
                    return value
            if self.truncated:
                self.done = True
                raise StopIteration
            try:
                chunk = next(self.chunks)
            except StopIteration:
                if self.buf.strip() and not self.started:
                    self.error = self.error or "Open data did not return a JSON array."
                self.done = True
                raise
            piece = _as_text(chunk)
            incoming = len(piece.encode("utf-8"))
            if self.total + incoming > self.max_bytes:
                keep = self.max_bytes - self.total
                if keep > 0:
                    piece = piece.encode("utf-8")[:keep].decode("utf-8", "ignore")
                    self.buf += piece
                    self.total += len(piece.encode("utf-8"))
                self.truncated = True
                continue
            self.buf += piece
            self.total += incoming
        raise StopIteration
