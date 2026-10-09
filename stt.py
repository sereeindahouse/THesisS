"""CPU first: transcribe a real file and retain raw text plus timing."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('audio')
    p.add_argument('--model', default='small')
    p.add_argument('--output', default='results/q01-stt.json')
    p.add_argument('--without-timestamps', action='store_true', help='Text-only decoding for a model trained without timestamps.')
    p.add_argument('--temperature', type=float, help='Fixed decoder temperature; omitted keeps the previous runtime fallback.')
    p.add_argument('--vad-filter', action='store_true')
    p.add_argument('--no-previous-text', action='store_true')
    p.add_argument('--local-only', action='store_true', help='Require already downloaded model files.')
    a = p.parse_args()
    if a.temperature is not None and not 0 <= a.temperature <= 1:
        p.error('temperature must be between 0 and 1.')
    audio = Path(a.audio)
    if not audio.is_file():
        p.error(f'Audio file not found: {audio}')
    output = Path(a.output)
    if output.exists():
        p.error('Output already exists. Choose a new filename for this run.')
    from faster_whisper import WhisperModel
    print('Локал STT модель ачаалж байна...' if a.local_only else 'STT модель ачаалж байна. Анхны таталтад интернет хэрэгтэй байж болно.', flush=True)
    load_start = time.perf_counter()
    local_small = Path(__file__).resolve().parent / 'models/faster-whisper-small'
    local_files = ('model.bin', 'config.json', 'tokenizer.json')
    has_vocabulary = any((local_small / name).is_file() for name in ('vocabulary.txt', 'vocabulary.json'))
    model_source = (str(local_small) if a.model == 'small' and
                    all((local_small / name).is_file() for name in local_files) and has_vocabulary else a.model)
    print(f'Model source: {model_source}', flush=True)
    model = WhisperModel(model_source, device='cpu', compute_type='int8', local_files_only=a.local_only)
    load_seconds = time.perf_counter() - load_start
    print('Model ready. Transcribing audio locally...', flush=True)
    start = time.perf_counter()
    decoding = dict(language='mn', task='transcribe', beam_size=5,
                    vad_filter=a.vad_filter, without_timestamps=a.without_timestamps,
                    condition_on_previous_text=not a.no_previous_text)
    if a.temperature is not None:
        decoding['temperature'] = a.temperature
    segments, info = model.transcribe(str(audio), **decoding)
    # segments is lazy: consume it before stopping the clock.
    rows = [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in segments]
    seconds = time.perf_counter() - start
    result = {'audio': str(audio), 'model': a.model, 'model_source': model_source, 'device': 'cpu',
              'compute_type': 'int8', 'actual_compute_type': model.model.compute_type,
              'requested_language': 'mn', 'decoding': decoding,
              'temperature_policy': 'fixed' if a.temperature is not None else 'runtime_default_fallback',
              'local_files_only': a.local_only,
              'created_at': datetime.now(timezone.utc).isoformat(),
              'model_load_seconds': load_seconds, 'transcription_seconds': seconds,
              'audio_seconds': info.duration,
              'real_time_factor': seconds / info.duration if info.duration else None,
              'text': ' '.join(s['text'] for s in rows), 'segments': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(result['text'])
    print(f'Transcription: {seconds:.2f}s; model loading: {load_seconds:.2f}s')
    print(f'Saved: {output}')

if __name__ == '__main__':
    main()
