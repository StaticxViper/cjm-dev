"""Social preview card for the Moulton site. Uses only the Python standard library."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

WIDTH = 1200
HEIGHT = 630
GREEN = (8, 12, 11)
CREAM = (243, 241, 234)

# Glyphs use y-down coordinates inside a 140-unit box. Baseline sits at y=132.
_GLYPHS: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {}


def _arc(cx: float, cy: float, radius: float, start: float, end: float, steps: int = 28) -> list[tuple[float, float]]:
    points = []
    for step in range(steps + 1):
        angle = start + (end - start) * step / steps
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _register(char: str, advance: float, strokes: list[list[tuple[float, float]]]) -> None:
    _GLYPHS[char] = (advance, strokes)


def _build_glyphs() -> None:
    if _GLYPHS:
        return
    _register("M", 118, [
        [(16, 132), (16, 10)],
        [(16, 10), (58, 74)],
        [(58, 74), (100, 10)],
        [(100, 10), (100, 132)],
    ])
    _register("o", 96, [_arc(48, 90, 38, 0, math.tau)])
    _register("u", 96, [
        [(14, 52), (14, 96)],
        _arc(48, 96, 34, math.pi, 0),
        [(82, 96), (82, 52)],
    ])
    _register("l", 48, [[(24, 8), (24, 132)]])
    _register("t", 72, [
        [(28, 18), (28, 132)],
        [(8, 58), (58, 58)],
    ])
    _register("n", 100, [
        [(16, 132), (16, 54)],
        [(16, 78)] + _arc(52, 78, 36, math.pi, math.tau) + [(88, 78), (88, 132)],
    ])
    _register("O", 116, [_arc(58, 72, 50, 0, math.tau)])
    _register("U", 110, [
        [(16, 12), (16, 84)],
        _arc(55, 84, 39, math.pi, 0),
        [(94, 84), (94, 12)],
    ])
    _register("L", 86, [
        [(18, 12), (18, 132)],
        [(18, 132), (74, 132)],
    ])
    _register("T", 96, [
        [(48, 12), (48, 132)],
        [(12, 12), (84, 12)],
    ])
    _register("N", 112, [
        [(16, 132), (16, 12)],
        [(16, 12), (96, 132)],
        [(96, 132), (96, 12)],
    ])
    _register("C", 100, [_arc(62, 72, 46, 0.55, math.tau - 0.55)])
    _register("J", 78, [
        [(14, 22), (64, 22)],
        [(50, 22), (50, 96)],
        _arc(32, 96, 18, 0, math.pi),
    ])
    _register("V", 100, [
        [(12, 12), (50, 132)],
        [(50, 132), (88, 12)],
    ])
    _register("E", 90, [
        [(16, 12), (16, 132)],
        [(16, 12), (82, 12)],
        [(16, 72), (66, 72)],
        [(16, 132), (82, 132)],
    ])
    _register("R", 100, [
        [(16, 132), (16, 12)],
        [(16, 12), (52, 12)] + _arc(52, 42, 30, -math.pi / 2, math.pi / 2) + [(16, 72)],
        [(40, 72), (90, 132)],
    ])
    _register("S", 92, [[
        (74, 30),
        (58, 14),
        (36, 14),
        (18, 28),
        (16, 46),
        (28, 62),
        (50, 70),
        (70, 80),
        (80, 98),
        (74, 118),
        (52, 130),
        (30, 126),
        (16, 110),
    ]])
    _register(" ", 36, [])
    _register("·", 40, [_arc(20, 74, 5, 0, math.tau)])


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _fill_disk(buffer: bytearray, x: float, y: float, radius: float, color: tuple[int, int, int]) -> None:
    radius_i = int(math.ceil(radius))
    cx = int(round(x))
    cy = int(round(y))
    radius_sq = radius * radius
    red, green, blue = color
    for py in range(cy - radius_i, cy + radius_i + 1):
        if py < 0 or py >= HEIGHT:
            continue
        for px in range(cx - radius_i, cx + radius_i + 1):
            if px < 0 or px >= WIDTH:
                continue
            if (px - x) * (px - x) + (py - y) * (py - y) <= radius_sq:
                index = (py * WIDTH + px) * 3
                buffer[index:index + 3] = bytes((red, green, blue))


def _stroke(buffer: bytearray, points: list[tuple[float, float]], radius: float, color: tuple[int, int, int]) -> None:
    for start, end in zip(points, points[1:]):
        x0, y0 = start
        x1, y1 = end
        distance = max(abs(x1 - x0), abs(y1 - y0), 1.0)
        steps = max(int(distance), 1)
        for step in range(steps + 1):
            blend = step / steps
            _fill_disk(buffer, x0 + (x1 - x0) * blend, y0 + (y1 - y0) * blend, radius, color)


def _draw_text(
    buffer: bytearray,
    text: str,
    origin_x: float,
    origin_y: float,
    scale: float,
    radius: float,
    color: tuple[int, int, int],
) -> float:
    _build_glyphs()
    cursor = origin_x
    for char in text:
        advance, strokes = _GLYPHS[char]
        for stroke in strokes:
            scaled = [(cursor + x * scale, origin_y + y * scale) for x, y in stroke]
            _stroke(buffer, scaled, radius, color)
        cursor += advance * scale
    return cursor - origin_x


def _text_width(text: str, scale: float) -> float:
    _build_glyphs()
    return sum(_GLYPHS[char][0] for char in text) * scale


def write_og_png(path: Path) -> None:
    _build_glyphs()
    buffer = bytearray(GREEN * WIDTH * HEIGHT)
    word = "Moulton"
    word_scale = 1.05
    word_width = _text_width(word, word_scale)
    word_x = (WIDTH - word_width) / 2
    word_y = 168
    _draw_text(buffer, word, word_x, word_y, word_scale, 7.2, CREAM)

    line = "CJ MOULTON  ·  MOULTON VENTURES"
    line_scale = 0.34
    line_width = _text_width(line, line_scale)
    line_x = (WIDTH - line_width) / 2
    rule_y = word_y + 132 * word_scale + 36
    rule_half = 72
    _stroke(buffer, [(WIDTH / 2 - rule_half, rule_y), (WIDTH / 2 + rule_half, rule_y)], 1.1, CREAM)
    _draw_text(buffer, line, line_x, rule_y + 22, line_scale, 2.5, CREAM)

    raw = bytearray()
    stride = WIDTH * 3
    for y in range(HEIGHT):
        raw.append(0)
        start = y * stride
        raw.extend(buffer[start:start + stride])
    png = b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        _chunk(b"IEND", b""),
    ])
    path.write_bytes(png)
