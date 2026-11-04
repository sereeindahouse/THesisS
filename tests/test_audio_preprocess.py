from array import array
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
import wave

from audio_preprocess import clean_pcm, clean_wav, enabled

RATE = 16000


def tone(seconds, amplitude):
    count = int(RATE * seconds)
    return array('h', (int(amplitude * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(count)))


def silence(seconds):
    return array('h', [0] * int(RATE * seconds))


class AudioPreprocessTests(unittest.TestCase):
    def test_trailing_silence_is_trimmed_with_padding_and_quiet_speech_is_raised(self):
        samples = silence(1) + tone(2, 8000) + silence(6)
        pcm, report = clean_pcm(samples.tobytes(), RATE)
        out = array('h'); out.frombytes(pcm)
        self.assertTrue(report['changed'])
        self.assertAlmostEqual(report['output_seconds'], 2.6, delta=0.05)   # 2 s speech + 2 x 0.3 s pad
        self.assertAlmostEqual(max(abs(x) for x in out) / 32768, 0.7, delta=0.02)
        self.assertLessEqual(report['gain'], 4.0)

    def test_loud_audio_is_not_turned_down_and_gain_is_capped(self):
        _, loud = clean_pcm(tone(1, 30000).tobytes(), RATE)
        self.assertEqual(loud['gain'], 1.0)
        _, faint = clean_pcm(tone(1, 500).tobytes(), RATE)
        self.assertEqual(faint['gain'], 4.0)

    def test_all_silent_input_is_returned_unchanged(self):
        raw = silence(2).tobytes()
        pcm, report = clean_pcm(raw, RATE)
        self.assertEqual(pcm, raw)
        self.assertFalse(report['changed'])

    def test_wav_round_trip_keeps_format_and_rejects_stereo(self):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(44100)
            handle.writeframes((silence(1) + tone(1, 2000)).tobytes())
        data, report = clean_wav(buffer.getvalue())
        with wave.open(io.BytesIO(data)) as handle:
            self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()), (1, 2, 44100))
        self.assertTrue(report['changed'])
        stereo = io.BytesIO()
        with wave.open(stereo, 'wb') as handle:
            handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(RATE)
            handle.writeframes(b'\0\0\0\0' * 10)
        with self.assertRaises(ValueError):
            clean_wav(stereo.getvalue())

    def test_switch_is_off_unless_exactly_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(enabled(root))
            (root / 'config').mkdir()
            path = root / 'config/stt-audio-cleanup.json'
            for value, expected in ((dict(enabled=False), False), (dict(enabled='yes'), False),
                                    ('{broken', False), (dict(enabled=True), True)):
                path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
                self.assertIs(enabled(root), expected)


if __name__ == '__main__':
    unittest.main()
