from __future__ import annotations

import struct
import wave

import pytest

from splicr.storage import LocalJobStorage


def test_assembles_raw_pcm_in_order_under_one_wav_header(tmp_path) -> None:
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    first = struct.pack("<hh", 1, 2)
    second = struct.pack("<hh", 3, 4)
    first_path = storage.write_chunk("job", 0, first)
    second_path = storage.write_chunk("job", 1, second)

    output = storage.assemble_wav("job", [first_path, second_path])

    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        assert wav_file.getnframes() == 4
        assert wav_file.readframes(4) == first + second


def test_rejects_partial_pcm_frame(tmp_path) -> None:
    storage = LocalJobStorage(tmp_path / "jobs")

    with pytest.raises(ValueError, match="aligned"):
        storage.write_chunk("job", 0, b"x")


def test_partial_wav_uses_a_distinct_snapshot_path(tmp_path) -> None:
    storage = LocalJobStorage(tmp_path / "jobs")
    checkpoint = storage.write_chunk("job", 0, struct.pack("<hh", 1, 2))

    partial = storage.assemble_partial_wav("job", [checkpoint])

    assert partial == storage.partial_output_path("job")
    assert partial.is_file()
    assert not storage.output_path("job").exists()
