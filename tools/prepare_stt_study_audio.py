"""Make a NEW mono16kHz PCM16 WAV from an existing <=30s, <=8MiB recording.

Uses the demo's bounded local WAV/WebM/Ogg/MP4 decoder. The original is preserved;
no microphone, ASR, network, model, transcript, consent or human-review action is
performed. Both output parent directories must already exist. New WAV and JSON
provenance files are created exclusively, never overwritten.
If writing fails after reserving a name, files are LEFT UNTOUCHED: do not use
them as a completed pair; choose fresh output names. No path-based cleanup runs.

python tools/prepare_stt_study_audio.py --input ORIGINAL --output NEW.wav
Optional --provenance NEW.json; default: NEW.wav.provenance.json.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import voice_runtime as voice

_SOURCE = Path(__file__).resolve()
_CODE_SHA256 = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()


class IncompletePreparationError(ValueError):
    """An unsuccessful attempt reserved names; their contents must be preserved."""
    def __init__(self, paths):
        self.reserved_paths = [str(path) for path in paths]
        super().__init__('Preparation did not complete. Reserved output paths were left untouched: '
                         + ', '.join(self.reserved_paths)
                         + '. They are not a completed WAV/provenance pair; choose fresh names.')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_source(path):
    with path.open('rb') as handle:
        payload = handle.read(voice.MAX_AUDIO_BYTES + 1)
    if len(payload) > voice.MAX_AUDIO_BYTES:
        raise ValueError('Original recording exceeds8MiB; shorten it without replacing the original.')
    return payload


def _resolve(path, strict=False):
    try:
        return Path(path).resolve(strict=strict)
    except RuntimeError as exc:
        raise ValueError('Unresolvable path or symbolic-link loop.') from exc


def _destinations(source, output, provenance):
    paths = [Path(output), Path(provenance)]
    resolved = [_resolve(p) for p in paths]
    if source in resolved or resolved[0] == resolved[1]:
        raise ValueError('Source, output WAV and provenance must be three different paths.')
    if paths[0].suffix.casefold() != '.wav' or paths[1].suffix.casefold() != '.json':
        raise ValueError('Use a .wav output and .json provenance destination.')
    for original, absolute in zip(paths, resolved):
        if os.path.lexists(original):
            raise FileExistsError('Destination already exists; preserve it: ' + str(original))
        if not absolute.parent.is_dir():
            raise ValueError('Create the output parent directory first: ' + str(absolute.parent))
    return resolved


def _code_binding():
    loaded = dict(voice._LOADED_ARTIFACT_SHA256)
    if (_sha(_SOURCE.read_bytes()) != _CODE_SHA256
            or any(not digest or _sha((ROOT / name).read_bytes()) != digest
                   for name, digest in loaded.items())):
        raise ValueError('Loaded preparation/voice/STT code differs from its source hash; restart with coordinated code.')
    return {'tools/prepare_stt_study_audio.py': _CODE_SHA256, **loaded}


def _source_metadata(payload, demuxer):
    import av
    options = dict(mode='r', format=demuxer)
    if int(av.__version__.split('.', 1)[0]) < 19:
        options['metadata_errors'] = 'ignore'
    if demuxer == 'mov':
        options['options'] = {'enable_drefs': '0'}
    with av.open(io.BytesIO(payload), **options) as container:
        streams = list(container.streams.audio)
        if len(streams) != 1:
            raise ValueError('Require exactly one audio stream.')
        codec = streams[0].codec_context
        layout = getattr(codec, 'layout', None)
        return dict(container=container.format.name, forced_demuxer=demuxer,
                    sample_rate=getattr(codec, 'sample_rate', None) or None,
                    channels=len(layout.channels) if layout is not None else None,
                    codec=getattr(codec, 'name', None), decoder_library='PyAV',
                    decoder_version=av.__version__)


def _wav(pcm):
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 30 * 16000 * 2:
        raise ValueError('Decoder did not return bounded complete PCM16 frames.')
    payload = voice._wav_bytes(pcm)
    with wave.open(io.BytesIO(payload), 'rb') as handle:
        frames = len(pcm) // 2
        if ((handle.getnchannels(), handle.getsampwidth(), handle.getframerate(),
             handle.getnframes(), handle.getcomptype()) != (1, 2, 16000, frames, 'NONE')
                or handle.readframes(frames + 1) != pcm or len(payload) != 44 + len(pcm)):
            raise ValueError('Derived WAV header or frame payload differs from mono16kHz PCM16.')
    return payload, frames


def _exclusive_pair(paths, payloads):
    # Reserve BOTH names before writing either payload. Never delete by name on
    # failure: another writer can replace a path between any stat and unlink.
    handles, failure = [], None
    try:
        for path in paths:
            handle = path.open('xb')
            handles.append(handle)
        for handle, payload in zip(handles, payloads):
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    except BaseException as exc:
        failure = exc
    finally:
        for handle in handles:
            try:
                handle.close()
            except BaseException as exc:
                failure = failure or exc
    if failure is not None:
        if handles:
            raise IncompletePreparationError(paths[:len(handles)]) from failure
        raise failure


def prepare_audio(input_path, output_path, provenance_path=None):
    """Preserve an original recording and return the new audio/provenance hashes."""
    source = _resolve(input_path, strict=True)
    if not source.is_file():
        raise ValueError('Input must be an existing recording file.')
    provenance_path = provenance_path or Path(str(output_path) + '.provenance.json')
    outputs = _destinations(source, output_path, provenance_path)  # Before decode or writes.
    code = _code_binding()
    payload = _read_source(source)
    source_sha = _sha(payload)
    demuxer, mime = voice._audio_format(payload, None)
    pcm = voice._decode_pcm(payload, demuxer)
    metadata = _source_metadata(payload, demuxer)
    derived, frames = _wav(pcm)
    if _sha(_read_source(source)) != source_sha:
        raise ValueError('Original recording changed during preparation; no output was written.')
    if _code_binding() != code:
        raise ValueError('Loaded code binding changed during preparation.')
    evidence = dict(schema_version=1, artifact_kind='derived_stt_study_audio',
        prepared_utc=datetime.now(timezone.utc).isoformat(),
        source=dict(filename=source.name, sha256=source_sha, bytes=len(payload),
                    mime=mime, **metadata),
        output=dict(filename=outputs[0].name, sha256=_sha(derived), bytes=len(derived),
                    sample_rate=16000, channels=1, sample_format='pcm16',
                    frames=frames, duration_seconds=frames / 16000),
        loaded_code_sha256=code,
        limits=dict(maximum_input_bytes=voice.MAX_AUDIO_BYTES,
                    maximum_seconds=voice.MAX_AUDIO_SECONDS,
                    decode_timeout_seconds=voice.DECODE_TIMEOUT_SECONDS),
        source_bytes_preserved=True, local_decode_only=True, no_asr_performed=True,
        no_transcript_created=True, microphone_activated=False, consent_asserted=False,
        human_transcript_review_performed=False, measured_recognition_improvement=None,
        must_not_use_if_command_failed=True)
    encoded = (json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    _exclusive_pair(outputs, (derived, encoded))
    return dict(output=str(outputs[0]), audio_sha256=_sha(derived), frames=frames,
                duration_seconds=frames / 16000, provenance=str(outputs[1]),
                provenance_sha256=_sha(encoded), no_asr_performed=True, completed=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provenance', type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = prepare_audio(args.input, args.output, args.provenance)
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps(dict(ok=False, error=str(exc), usable_outputs=False,
                              incomplete_output_paths=getattr(exc, 'reserved_paths', [])), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
