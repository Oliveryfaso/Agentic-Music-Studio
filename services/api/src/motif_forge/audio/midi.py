"""Dependency-free deterministic Standard MIDI File export for ArrangementIR."""

from __future__ import annotations

import struct

from motif_forge.domain.ir import ArrangementIR, NoteClip


def _vlq(value: int) -> bytes:
    encoded = [value & 0x7F]
    value >>= 7
    while value:
        encoded.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(encoded))


def _track_chunk(events: list[tuple[int, int, bytes]]) -> bytes:
    payload = bytearray()
    previous = 0
    for tick, _, event in sorted(events, key=lambda item: (item[0], item[1], item[2])):
        payload.extend(_vlq(tick - previous))
        payload.extend(event)
        previous = tick
    payload.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + struct.pack(">I", len(payload)) + bytes(payload)


def arrangement_to_midi(arrangement: ArrangementIR) -> bytes:
    """Encode tempo/meta plus one MIDI track per instrument track."""

    tempo = round(60_000_000 / arrangement.tempo_map[0].bpm)
    meta = [
        (0, 0, b"\xff\x51\x03" + tempo.to_bytes(3, "big")),
        (0, 1, b"\xff\x58\x04\x04\x02\x18\x08"),
    ]
    chunks = [_track_chunk(meta)]
    for channel, track in enumerate(
        sorted(arrangement.tracks, key=lambda item: str(item.track_id))
    ):
        events: list[tuple[int, int, bytes]] = []
        midi_channel = channel % 16
        for clip in track.clips:
            if not isinstance(clip, NoteClip):
                continue
            for note in clip.notes:
                start = clip.start_tick + note.start_tick
                end = start + note.duration_tick
                events.append((start, 1, bytes((0x90 | midi_channel, note.pitch, note.velocity))))
                events.append((end, 0, bytes((0x80 | midi_channel, note.pitch, 0))))
        chunks.append(_track_chunk(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), arrangement.ppq)
    return header + b"".join(chunks)
