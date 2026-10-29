#!/usr/bin/env python3
"""Remux a controlled H.264 file to local RTSP at its source rate, on CPU only."""

from __future__ import annotations

import argparse
import time
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit


def publish(filename: Path, url: str) -> None:
    import av

    parsed = urlsplit(url)
    if (
        parsed.scheme != "rtsp"
        or parsed.hostname != "172.17.0.1"
        or parsed.port != 18554
        or parsed.path not in ("/city-traffic", "/city-pedestrians")
    ):
        raise ValueError(
            "This fixture publisher only writes the controlled local replay paths"
        )
    clock = time.monotonic()
    offset = 0
    output = None
    out_stream = None
    try:
        while True:
            with av.open(str(filename)) as source:
                stream = source.streams.video[0]
                if stream.codec_context.name != "h264":
                    raise ValueError("This remux-only fixture requires H.264")
                if output is None:
                    output = av.open(
                        url, "w", format="rtsp", options={"rtsp_transport": "tcp"}
                    )
                    out_stream = output.add_stream_from_template(stream)
                first_dts = None
                loop_end = offset
                for packet in source.demux(stream):
                    if packet.dts is None or packet.pts is None:
                        continue
                    first_dts = packet.dts if first_dts is None else first_dts
                    base = packet.time_base or stream.time_base or Fraction(1, 90000)
                    local_dts = packet.dts - first_dts
                    target = clock + float((offset + local_dts) * base)
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    packet.pts = packet.pts - first_dts + offset
                    packet.dts = local_dts + offset
                    loop_end = max(loop_end, packet.dts + max(1, packet.duration))
                    packet.stream = out_stream
                    output.mux(packet)
                if first_dts is None:
                    raise ValueError("No usable H.264 packets")
                offset = loop_end
    finally:
        if output is not None:
            output.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--url", required=True)
    arguments = parser.parse_args()
    publish(arguments.file, arguments.url)
