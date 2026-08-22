"""Play a media file through the real default output device for loopback tests.

This helper never passes decoded samples to LiveSub. PyAV decodes the selected
test recording, sounddevice renders it through Windows, and LiveSub must capture
that rendered signal independently through WASAPI loopback.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import av
import numpy as np
import sounddevice as sd


def play(path: Path, limit_seconds: float | None, delay_seconds: float) -> None:
    if delay_seconds:
        time.sleep(delay_seconds)
    rendered_samples = 0
    sample_rate = 48_000
    maximum_samples = (
        round(limit_seconds * sample_rate) if limit_seconds is not None else None
    )
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=sample_rate)
    with av.open(str(path)) as container, sd.OutputStream(
        samplerate=sample_rate, channels=2, dtype="float32", latency="low"
    ) as output:
        for decoded in container.decode(audio=0):
            for frame in resampler.resample(decoded):
                samples = np.ascontiguousarray(frame.to_ndarray().T, dtype=np.float32)
                if maximum_samples is not None:
                    remaining = maximum_samples - rendered_samples
                    if remaining <= 0:
                        return
                    samples = samples[:remaining]
                output.write(samples)
                rendered_samples += samples.shape[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--delay", type=float, default=0.0)
    arguments = parser.parse_args()
    if not arguments.path.is_file():
        parser.error(f"media file not found: {arguments.path}")
    play(arguments.path, arguments.seconds, arguments.delay)
