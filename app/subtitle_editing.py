from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from subtitle_io import SubtitleCue, TranslatedCue


def validate_cue_sequence(
    source_cues: Sequence[SubtitleCue],
    translated_cues: Sequence[TranslatedCue],
) -> None:
    if len(source_cues) != len(translated_cues):
        raise ValueError(
            f"Cue count changed: source has {len(source_cues)}, translated data has {len(translated_cues)}"
        )
    for expected, translated in zip(source_cues, translated_cues):
        if translated.source != expected:
            raise ValueError(f"Original cue text, number or timestamp changed for cue {expected.index}")


def edit_translation(
    source_cues: Sequence[SubtitleCue],
    translated_cues: Sequence[TranslatedCue],
    cue_index: int,
    text: str,
) -> list[TranslatedCue]:
    validate_cue_sequence(source_cues, translated_cues)
    if cue_index < 1 or cue_index > len(source_cues):
        raise IndexError(f"Cue number out of range: {cue_index}")
    updated = list(translated_cues)
    current = updated[cue_index - 1]
    updated[cue_index - 1] = replace(current, translation=str(text))
    validate_cue_sequence(source_cues, updated)
    return updated


def revert_translation(
    source_cues: Sequence[SubtitleCue],
    current_cues: Sequence[TranslatedCue],
    gemini_cues: Sequence[TranslatedCue],
    cue_index: int,
) -> list[TranslatedCue]:
    validate_cue_sequence(source_cues, current_cues)
    validate_cue_sequence(source_cues, gemini_cues)
    if cue_index < 1 or cue_index > len(source_cues):
        raise IndexError(f"Cue number out of range: {cue_index}")
    updated = list(current_cues)
    updated[cue_index - 1] = replace(gemini_cues[cue_index - 1])
    return updated


def revert_all_translations(
    source_cues: Sequence[SubtitleCue],
    current_cues: Sequence[TranslatedCue],
    gemini_cues: Sequence[TranslatedCue],
) -> list[TranslatedCue]:
    validate_cue_sequence(source_cues, current_cues)
    validate_cue_sequence(source_cues, gemini_cues)
    return list(gemini_cues)
