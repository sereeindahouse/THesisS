"""Optional cleanup of a mono 16-bit WAV before cloud STT: trim silence, even the level.

Pure stdlib; no provider, model or file access. The 13 dev clips (10/29) had
4-8 s of trailing silence in 12 s and peaks 4-16 dB below full scale. Whether
this helps Gemini is measured by tools/compare_gemini_stt_v2.py; production
uses it only if config/stt-audio-cleanup.json is enabled.
"""
from __future__ import annotations

from array import array
import io
import json
import math
from pathlib import Path
import sys
import wave

CONFIG_PATH = 'config/stt-audio-cleanup.json'
FRAME_MS = 20
PAD_MS = 300            # keep a little silence so the first/last syllable is not cut
SILENCE_RATIO = 0.05    # frame RMS below 5% of the loudest frame counts as silence
TARGET_PEAK = 0.7       # about -3 dBFS
MAX_GAIN = 4.0          # never amplify noise more than 12 dB


def _samples(pcm):
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def _pcm(samples):
    if sys.byteorder != 'little':
        samples = array('h', samples)
        samples.byteswap()
    return samples.tobytes()


def clean_pcm(pcm, rate):
    """Return (pcm, report). Silent or tiny input is returned unchanged."""
    samples = _samples(pcm)
    frame = max(1, rate * FRAME_MS // 1000)
    levels = [math.sqrt(sum(x * x for x in samples[i:i + frame]) / len(samples[i:i + frame]))
              for i in range(0, len(samples), frame)]
    report = dict(input_seconds=round(len(samples) / rate, 3), trimmed_seconds=0.0, gain=1.0, changed=False)
    if not levels or max(levels) == 0:
        return pcm, report
    threshold = max(levels) * SILENCE_RATIO
    voiced = [i for i, level in enumerate(levels) if level > threshold]
    pad = PAD_MS // FRAME_MS
    start = max(0, voiced[0] - pad) * frame
    end = min(len(samples), (voiced[-1] + 1 + pad) * frame)
    kept = samples[start:end]
    peak = max(abs(x) for x in kept) / 32768
    gain = min(MAX_GAIN, TARGET_PEAK / peak) if peak else 1.0
    gain = gain if gain > 1.0 else 1.0   # only raise quiet audio; loud audio is left alone
    if gain > 1.0:
        kept = array('h', (max(-32768, min(32767, round(x * gain))) for x in kept))
    report.update(trimmed_seconds=round((len(samples) - len(kept)) / rate, 3), gain=round(gain, 3),
                  output_seconds=round(len(kept) / rate, 3), changed=gain > 1.0 or len(kept) != len(samples))
    return _pcm(kept), report


def clean_wav(data):
    """Mono 16-bit WAV bytes in, cleaned WAV bytes and a report out."""
    with wave.open(io.BytesIO(data)) as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError('Expected mono 16-bit WAV.')
        rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    cleaned, report = clean_pcm(pcm, rate)
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(cleaned)
    return output.getvalue(), report


def enabled(root):
    """OFF unless the config file says exactly {"enabled": true}; errors stay OFF."""
    try:
        data = json.loads((Path(root) / CONFIG_PATH).read_text(encoding='utf-8'))
        return isinstance(data, dict) and data.get('enabled') is True
    except (OSError, ValueError):
        return False
