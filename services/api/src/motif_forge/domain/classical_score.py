"""Strict, bounded MusicXML melody import; unsupported semantics never disappear."""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import UUID, uuid5
from xml.etree import ElementTree as ET

from pydantic import Field

from motif_forge.domain.ir import (
    ArrangementIRV2,
    DomainModel,
    KeyPoint,
    LockedRange,
    MeterPoint,
    MusicalMode,
    NoteClip,
    NoteEvent,
    PianoRenderProfile,
    ProvenanceRef,
    Section,
    TempoPoint,
    Track,
    TrackRole,
    TrackType,
)


class ScoreNote(DomainModel):
    note_id: UUID
    measure_id: str
    source_note_id: str
    pitch: int
    start_tick: int
    duration_tick: int


class ParsedScore(DomainModel):
    source_sha256: str
    measure_count: int
    bpm: float
    beats: int
    tonic: str
    notes: tuple[ScoreNote, ...] = Field(max_length=1000)


def parse_musicxml(data: bytes, *, namespace: UUID) -> ParsedScore:
    if len(data) > 128_000:
        raise ValueError("SCORE_RESOURCE_LIMIT")
    without_declaration = re.sub(rb"^\s*<\?xml[^?]*\?>", b"", data, count=1)
    if b"<!" in data or b"<?" in without_declaration:
        raise ValueError("SCORE_XML_UNSAFE")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("SCORE_XML_INVALID") from exc
    if root.tag != "score-partwise" or root.attrib.get("version") not in ("3.1", "4.0"):
        raise ValueError("SCORE_FEATURE_UNSUPPORTED:format")
    forbidden = {
        "tie",
        "tied",
        "time-modification",
        "chord",
        "backup",
        "forward",
        "transpose",
        "repeat",
        "ending",
        "grace",
        "cue",
        "notations",
        "unpitched",
        "staff",
        "staves",
    }
    allowed = {
        "score-partwise",
        "work",
        "work-title",
        "identification",
        "creator",
        "rights",
        "part-list",
        "score-part",
        "part-name",
        "part",
        "measure",
        "attributes",
        "divisions",
        "key",
        "fifths",
        "mode",
        "time",
        "beats",
        "beat-type",
        "direction",
        "sound",
        "note",
        "pitch",
        "step",
        "alter",
        "octave",
        "duration",
        "type",
        "dot",
        "rest",
        "voice",
    }
    elements = list(root.iter())
    if len(elements) > 12000:
        raise ValueError("SCORE_RESOURCE_LIMIT")
    if any(e.tag in forbidden or e.tag not in allowed for e in elements):
        raise ValueError("SCORE_FEATURE_UNSUPPORTED")
    if len(root.findall("part")) != 1 or len(root.findall("./part-list/score-part")) != 1:
        raise ValueError("SCORE_FEATURE_UNSUPPORTED:parts")
    measures = root.findall("./part/measure")
    if not 1 <= len(measures) <= 32:
        raise ValueError("SCORE_RESOURCE_LIMIT")
    first = measures[0]
    try:
        divisions = int(first.findtext("./attributes/divisions", "0"))
        beats = int(first.findtext("./attributes/time/beats", "0"))
        denominator = int(first.findtext("./attributes/time/beat-type", "0"))
        fifths = int(first.findtext("./attributes/key/fifths", "99"))
        mode = first.findtext("./attributes/key/mode", "major")
        bpm = float(first.find("./direction/sound").attrib["tempo"])  # type: ignore[union-attr]
    except (ValueError, KeyError, AttributeError) as exc:
        raise ValueError("SCORE_HEADER_INVALID") from exc
    if (
        not 1 <= divisions <= 9600
        or beats not in (3, 4)
        or denominator != 4
        or mode != "major"
        or fifths not in (0, 1)
        or not 40 <= bpm <= 220
    ):
        raise ValueError("SCORE_FEATURE_UNSUPPORTED:meter-key-tempo")
    notes = []
    seen = set()
    measure_ids = set()
    voices = set()
    for index, measure in enumerate(measures):
        if index and (
            measure.find("attributes") is not None or measure.find("direction") is not None
        ):
            raise ValueError("SCORE_FEATURE_UNSUPPORTED:changes")
        measure_id = measure.attrib.get("id", f"m{index + 1:02}")
        if measure_id in measure_ids or measure.attrib.get("implicit") == "yes":
            raise ValueError("SCORE_FEATURE_UNSUPPORTED:measure")
        measure_ids.add(measure_id)
        cursor = 0
        for position, element in enumerate(measure.findall("note")):
            if element.attrib.get("print-object") == "no":
                raise ValueError("SCORE_FEATURE_UNSUPPORTED:hidden-note")
            voices.add(element.findtext("voice", "1"))
            if len(voices) > 1:
                raise ValueError("SCORE_FEATURE_UNSUPPORTED:voices")
            source_id = element.attrib.get("id", f"{measure_id}-n{position + 1:02}")
            if source_id in seen:
                raise ValueError("SCORE_NOTE_ID_DUPLICATE")
            seen.add(source_id)
            try:
                units = int(element.findtext("duration", "0"))
                if units <= 0 or units * 480 % divisions:
                    raise ValueError("SCORE_TIME_NOT_EXACT")
                duration = units * 480 // divisions
                if element.find("rest") is None:
                    pitch = element.find("pitch")
                    if pitch is None:
                        raise ValueError("SCORE_PITCH_INVALID")
                    step = pitch.findtext("step", "")
                    octave = int(pitch.findtext("octave", "-9"))
                    alter = int(pitch.findtext("alter", "0"))
                    if step not in "CDEFGAB" or len(step) != 1 or alter not in (-1, 0, 1):
                        raise ValueError("SCORE_PITCH_INVALID")
                    midi = (
                        (octave + 1) * 12
                        + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
                        + alter
                    )
                    if not 21 <= midi <= 108:
                        raise ValueError("SCORE_PITCH_INVALID")
                    notes.append(
                        ScoreNote(
                            note_id=uuid5(
                                namespace,
                                f"score:{sha256(data).hexdigest()}:{measure_id}:{source_id}",
                            ),
                            measure_id=measure_id,
                            source_note_id=source_id,
                            pitch=midi,
                            start_tick=index * beats * 480 + cursor,
                            duration_tick=duration,
                        )
                    )
            except (ValueError, KeyError) as exc:
                raise ValueError("SCORE_NOTE_INVALID:" + str(exc)) from exc
            cursor += duration
        if cursor != beats * 480:
            raise ValueError("SCORE_MEASURE_DURATION")
    if not notes or len(notes) > 1000:
        raise ValueError("SCORE_RESOURCE_LIMIT")
    return ParsedScore(
        source_sha256=sha256(data).hexdigest(),
        measure_count=len(measures),
        bpm=bpm,
        beats=beats,
        tonic="G" if fifths == 1 else "C",
        notes=tuple(notes),
    )


def score_to_arrangement(
    parsed: ParsedScore, *, project_id: UUID, source_ref: str
) -> ArrangementIRV2:
    duration = (
        (parsed.measure_count + 1) * parsed.beats * 480
    )  # explicit rest bar for bounded release

    def ident(name: str) -> UUID:
        return uuid5(project_id, "score-import.v1:" + name)

    return ArrangementIRV2(
        project_id=project_id,
        render_profile=PianoRenderProfile(),
        tempo_map=(TempoPoint(bpm=parsed.bpm),),
        time_signature_map=(MeterPoint(numerator=3 if parsed.beats == 3 else 4),),
        key_map=(
            KeyPoint(
                tick=0,
                tonic="G" if parsed.tonic == "G" else "C",
                mode=MusicalMode.MAJOR,
                confidence=1.0,
                source="reviewed-score",
            ),
        ),
        sections=(
            Section(
                section_id=ident("section"),
                start_tick=0,
                end_tick=duration,
                label="Original melody + release rest",
            ),
        ),
        provenance=(ProvenanceRef(kind="asset", ref=source_ref, version=parsed.source_sha256),),
        tracks=(
            Track(
                track_id=ident("melody"),
                track_type=TrackType.INSTRUMENT,
                name="原谱旋律",
                role=TrackRole.MELODY,
                instrument_ref="builtin:jazz-piano",
                locked_ranges=(LockedRange(start_tick=0, end_tick=duration),),
                clips=(
                    NoteClip(
                        clip_id=ident("clip"),
                        start_tick=0,
                        duration_tick=duration,
                        notes=tuple(
                            NoteEvent(
                                note_id=n.note_id,
                                pitch=n.pitch,
                                start_tick=n.start_tick,
                                duration_tick=n.duration_tick,
                                velocity=76,
                            )
                            for n in parsed.notes
                        ),
                    ),
                ),
            ),
        ),
    )
