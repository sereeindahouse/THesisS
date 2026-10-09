"""Download pinned public weights with exclusive ranges and full SHA256 checks."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def fetch_range(repo, revision, filename, total_size, start, end, directory):
    path = directory / f'{start:012d}.part'
    for attempt in range(6):
        received = path.stat().st_size if path.exists() else 0
        expected = end - start + 1
        if received > expected:
            raise ValueError('A retained range is larger than its pinned layout.')
        if received == expected:
            return
        offset = start + received
        url = f'https://huggingface.co/{repo}/resolve/{revision}/{filename}?download=true&range_start={offset}&range_end={end}'
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-{end}'})
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f'bytes {offset}-{end}/{total_size}':
                    raise ValueError('Server did not honor the exact pinned byte range.')
                with path.open('ab') as handle:
                    while received < expected:
                        block = response.read(min(1024 * 1024, expected - received))
                        if not block:
                            break
                        handle.write(block)
                        received += len(block)
            if received == expected:
                return
        except (OSError, urllib.error.URLError) as error:
            if attempt == 5:
                raise
            print(f'Range {start}: retry {attempt+1}, retained {received/1e6:.1f} MB ({type(error).__name__}).', flush=True)
    raise RuntimeError('Incomplete range retained for a future resume.')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default='Cafet/whisper-small-mongolian')
    parser.add_argument('--name', default='whisper-small-mn-cafet-hf')
    parser.add_argument('--metadata', type=Path, help='Pinned public metadata JSON; default uses local metadata or config/model-catalog.')
    args = parser.parse_args()
    metadata_path = args.metadata or ROOT / 'results/mongolian-model-research-20261009' / (args.repo.replace('/', '--') + '.json')
    if args.metadata is None and not metadata_path.is_file():
        metadata_path = ROOT / 'config/model-catalog' / (args.repo.replace('/', '--') + '.json')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert metadata['repo_id'] == args.repo
    directory = ROOT / 'models' / args.name
    model_root = (ROOT / 'models').resolve()
    if not directory.resolve().is_relative_to(model_root) or directory.resolve() == model_root:
        parser.error('Model output must be a subdirectory of models.')
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'active-download.lock'
    with lock.open('x', encoding='utf-8') as handle:
        json.dump(dict(pid=os.getpid(), repo=args.repo, revision=metadata['revision']), handle)
    try:
        weights = [file for file in metadata['files'] if file['rfilename'] == 'model.safetensors']
        if len(weights) != 1:
            raise ValueError('This downloader requires a single non-pickle safetensors checkpoint.')
        weight = weights[0]
        filename, size, sha = weight['rfilename'], weight['size'], weight['lfs']['sha256']
        revision = metadata['revision']
        assets = [file for file in metadata['files'] if '/' not in file['rfilename'] and
                  file['rfilename'].endswith(('.json', '.txt', '.md'))]
        for asset in assets:
            path = directory / asset['rfilename']
            if path.exists():
                assert path.stat().st_size == asset['size']
                continue
            with urllib.request.urlopen(f'https://huggingface.co/{args.repo}/resolve/{revision}/{asset["rfilename"]}', timeout=30) as response:
                data = response.read()
            assert len(data) == asset['size']
            path.write_bytes(data)
        final = directory / filename
        if not final.exists():
            chunks = directory / 'download-chunks'
            chunks.mkdir(exist_ok=True)
            layout_file = chunks / 'layout.json'
            layout = dict(repo=args.repo, revision=revision, size=size, sha256=sha, block_size=16 * 1024 * 1024)
            if layout_file.exists():
                assert json.loads(layout_file.read_text()) == layout
            else:
                layout_file.write_text(json.dumps(layout), encoding='utf-8')
            ranges = [(start, min(start+layout['block_size']-1, size-1)) for start in range(0,size,layout['block_size'])]
            started = time.monotonic()
            print(f'Exclusive PID {os.getpid()}: downloading {args.repo}, {size/1e6:.1f} MB, 8 ranges at a time.', flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                pending = {pool.submit(fetch_range, args.repo, revision, filename, size, start, end, chunks) for start,end in ranges}
                while pending:
                    done, pending = concurrent.futures.wait(pending, timeout=10, return_when=concurrent.futures.FIRST_EXCEPTION)
                    for future in done:
                        future.result()
                    retained = sum(path.stat().st_size for path in chunks.glob('*.part'))
                    print(f'{retained/1e6:.1f}/{size/1e6:.1f} MB ({retained/size:.0%}); {len(ranges)-len(pending)}/{len(ranges)} ranges; {time.monotonic()-started:.0f}s.', flush=True)
            assembled = directory / (filename + '.assembled')
            assert not assembled.exists()
            with assembled.open('xb') as target:
                for start,end in ranges:
                    part = chunks / f'{start:012d}.part'
                    assert part.stat().st_size == end-start+1
                    with part.open('rb') as source:
                        for block in iter(lambda: source.read(4 * 1024 * 1024),b''):
                            target.write(block)
            assert assembled.stat().st_size == size and digest(assembled) == sha, 'Full weight checksum does not match.'
            assembled.replace(final)
        assert digest(final) == sha
        manifest = dict(repo_id=args.repo, revision=revision, license=metadata['license'],
            created_at=datetime.now(timezone.utc).isoformat(), private_audio_uploaded=False,
            files={file['rfilename']:dict(size=(directory/file['rfilename']).stat().st_size, sha256=digest(directory/file['rfilename']))
                   for file in [weight,*assets]})
        (directory / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Verified source checkpoint ready: {directory}', flush=True)
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
