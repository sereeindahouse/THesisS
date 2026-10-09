"""Use the pinned, locally tested Mongolian development configuration."""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_choice(root=ROOT):
    choice_path = root / 'data/stt-model-choice.json'
    if not choice_path.is_file():
        choice_path = root / 'config/stt-development.json'
    choice = json.loads(choice_path.read_text(encoding='utf-8'))
    path = (root / choice['development_model_path']).resolve()
    if not path.is_relative_to((root / 'models').resolve()):
        raise ValueError('The selected model must be inside the local models directory.')
    manifest = json.loads((path / 'download-manifest.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256()
    with (path / 'model.bin').open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    expected = choice['model_sha256']
    if digest.hexdigest() != expected or manifest['files']['model.bin']['sha256'] != expected:
        raise ValueError('Selected model checksum differs from the tested configuration.')
    if (manifest['repo_id'], manifest['revision']) != (choice['source_repo'], choice['source_revision']):
        raise ValueError('Selected model source differs from the tested configuration.')
    return choice, path


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Туршиж сонгосон Монгол STT моделийг локал ажиллуулах')
    parser.add_argument('audio', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    audio = args.audio if args.audio.is_absolute() else ROOT / args.audio
    output = args.output or Path('results') / (audio.stem + '-mn-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    output = output if output.is_absolute() else ROOT / output
    if not audio.is_file():
        parser.error(f'Бичлэг олдсонгүй: {audio}')
    if output.exists():
        parser.error('Гаралтын файл байгаа тул шинэ нэр сонгоно уу.')
    choice, path = load_choice()
    expected = dict(language='mn', task='transcribe', beam_size=5, vad_filter=False,
                    temperature=0.0, without_timestamps=True, condition_on_previous_text=False)
    if choice['decoding'] != expected:
        parser.error('Сонгосон тохиргоо өөрчлөгдсөн; wrapper-ийг дахин шалгах шаардлагатай.')
    print('Монгол STT: ' + choice['source_repo'] + ' (хөгжүүлэлтийн урьдчилсан сонголт)', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'stt.py'), str(audio), '--model', str(path),
                    '--without-timestamps', '--temperature', '0', '--no-previous-text',
                    '--local-only', '--output', str(output)], check=True)


if __name__ == '__main__':
    main()
