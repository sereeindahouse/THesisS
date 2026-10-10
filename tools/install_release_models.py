"""Install pinned model Release archives without adding large files to Git."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = Path('config/releases/models-20261010.json')
MODEL_LAYOUTS = {
    'stt': ('faster-whisper-small-mn-cafet', 'model.bin'),
    'retrieval': ('multilingual-e5-small', 'model.safetensors'),
}
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com',
                  'objects.githubusercontent.com'}
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3 - 1


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def validate_record(record):
    layout = MODEL_LAYOUTS.get(record.get('kind'))
    if not layout or (record.get('model_directory'), record.get('weight_file')) != layout:
        raise ValueError('Unexpected model directory or weight filename.')
    name = record.get('name', '')
    if not name or name != Path(name).name or '/' in name or '\\' in name or ':' in name:
        raise ValueError('Archive name must be a plain filename.')
    size = record.get('size')
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ValueError('Archive size must be a positive value below 2 GiB.')
    for key in ('sha256', 'model_sha256'):
        value = record.get(key, '')
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Missing or invalid pinned SHA256.')
    url = urlsplit(record.get('url', ''))
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
            or not url.path.startswith('/sereeindahouse/THesisS/releases/download/')
            or url.path.split('/')[-1] != name or len(url.path.split('/')) != 7):
        raise ValueError('Only this repository GitHub Release asset URLs are allowed.')
    members = record.get('members')
    if not isinstance(members, list) or not members or len(set(members)) != len(members):
        raise ValueError('Catalog must contain unique archive member names.')
    for member in members:
        safe_member(member, record['model_directory'])
    if f"models/{layout[0]}/{layout[1]}" not in members:
        raise ValueError('Archive catalog omits the model weight.')


def safe_member(name, model_directory):
    if (not isinstance(name, str) or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe archive path.')
    parts = PurePosixPath(name).parts
    if len(parts) < 3 or parts[:2] != ('models', model_directory):
        raise ValueError('Unexpected archive model prefix.')
    return Path(*parts)


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if parsed.scheme != 'https' or parsed.hostname not in DOWNLOAD_HOSTS:
            raise ValueError('Unexpected Release download redirect.')
        return super().redirect_request(request, response, code, message, headers, new_url)


def download_archive(record, destination):
    opener = build_opener(SafeRedirectHandler())
    request = Request(record['url'], headers={'User-Agent': 'THesisS-model-installer'})
    received = 0
    with opener.open(request, timeout=60) as response, destination.open('xb') as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            received += len(block)
            if received > record['size']:
                raise ValueError('Downloaded archive exceeds pinned size.')
            output.write(block)


def install_record(record, root=ROOT, archive_dir=None):
    validate_record(record)
    root = Path(root).resolve()
    models = root / 'models'
    runtime = root / 'runtime'
    for folder in (models, runtime):
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):
            raise ValueError('Model or runtime directory escapes the project.')
    target = models / record['model_directory']
    if target.is_symlink():
        raise ValueError('Existing model directory is a symlink.')
    weight = target / record['weight_file']
    if target.exists():
        if weight.is_symlink() or not weight.is_file() or sha256(weight) != record['model_sha256']:
            raise ValueError('Existing model differs from the pinned weight; refusing overwrite.')
        return {'kind': record['kind'], 'model_directory': record['model_directory'],
                'status': 'existing_verified'}
    runtime.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-model-install-', dir=runtime) as scratch:
        scratch = Path(scratch)
        if archive_dir is None:
            archive = scratch / record['name']
            download_archive(record, archive)
        else:
            archive = Path(archive_dir) / record['name']
        if archive.stat().st_size != record['size'] or sha256(archive) != record['sha256']:
            raise ValueError('Archive size or SHA256 differs from the pinned release.')
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            names = [entry.filename for entry in entries]
            if len(set(name.casefold() for name in names)) != len(names):
                raise ValueError('Duplicate archive paths are forbidden.')
            for entry in entries:
                safe_member(entry.filename, record['model_directory'])
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('Archive directory entries and symlinks are forbidden.')
            if set(names) != set(record['members']):
                raise ValueError('Archive members differ from the pinned catalog.')
            for entry in entries:
                destination = scratch / safe_member(entry.filename, record['model_directory'])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_file, destination.open('xb') as output:
                    for block in iter(lambda: input_file.read(1024 * 1024), b''):
                        output.write(block)
        extracted = scratch / 'models' / record['model_directory']
        if sha256(extracted / record['weight_file']) != record['model_sha256']:
            raise ValueError('Extracted model weight differs from the pinned model.')
        if target.exists() or target.is_symlink():
            raise ValueError('Model appeared during installation; refusing overwrite.')
        extracted.rename(target)
    return {'kind': record['kind'], 'model_directory': record['model_directory'],
            'status': 'installed_verified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', nargs='?', default='all', choices=('stt', 'e5', 'all'))
    parser.add_argument('--archive-dir', type=Path, help='Use already downloaded ZIP files.')
    args = parser.parse_args()
    try:
        catalog = json.loads((ROOT / CATALOG_PATH).read_text(encoding='utf-8'))
        kinds = ('stt', 'retrieval') if args.model == 'all' else (('retrieval',) if args.model == 'e5' else ('stt',))
        records = [record for record in catalog['records'] if record.get('kind') in kinds]
        if {record['kind'] for record in records} != set(kinds) or len(records) != len(kinds):
            raise ValueError('Release catalog has missing or duplicate model entries.')
        for record in records:
            validate_record(record)
        results = [install_record(record, archive_dir=args.archive_dir) for record in records]
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Model installation failed: {error}\n')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
