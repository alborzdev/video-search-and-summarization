# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest

from utils.file_splitter import FileSplitter


@pytest.mark.parametrize("path", ["single.jpg", "first.jpg;second.jpg"])
def test_finite_image_chunk_preserves_requested_offsets_and_terminal_flags(path):
    chunks = []
    FileSplitter(
        path,
        FileSplitter.SplitMode.SEEK,
        chunk_duration_sec=2,
        start_pts=1_000_000_000,
        end_pts=3_000_000_000,
        media_file_info=SimpleNamespace(is_image=True),
        on_new_chunk=chunks.append,
    ).split()

    assert len(chunks) == 2
    assert chunks[0].start_pts == 1_000_000_000
    assert chunks[0].end_pts == 3_000_000_000
    assert chunks[0].is_first is True
    assert chunks[0].is_last is True
    assert chunks[1] is None
