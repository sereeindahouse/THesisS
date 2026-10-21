"""Offline deployment preflight; never download, infer, launch or expose a server.

Use the same model pins, snapshot validators and gateway route policy as the demo.
A successful local preflight is deliberately not a claim of stable HTTPS hosting,
online TTS availability, clean-machine reproduction or human answer quality.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata, util
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_release import ContentReleaseManager
from llm_runtime import _validated_base_url
from project_policy import ContentUsePolicy
from stt_mn import load_choice
from tools import manage_snapshot as snapshots
from tools.install_release_models import validate_record
from tools.serve_device_demo import allowed_path
from voice_runtime import EXPECTED_DECODING, PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256

ENTRYPOINTS = (
    'DEMO.cmd', 'open_demo.py', 'demo_server.py', 'voice_runtime.py', 'rag_runtime.py',
    'content_release.py', 'release_runtime.py', 'demo/index.html', 'demo/data.html',
    'demo/admin.html', 'demo/admin.js', 'demo/admin.css', 'tools/start_local_llm.py',
    'tools/manage_snapshot.py', 'tools/manage_content_release.py',
    'tools/start_public_demo.py', 'tools/serve_public_demo.py', 'tools/serve_device_demo.py',
)
MODULES = {'faster-whisper': 'faster_whisper', 'edge-tts': 'edge_tts',
           'sounddevice': 'sounddevice', 'scipy': 'scipy', 'ctranslate2': 'ctranslate2',
           'torch': 'torch', 'transformers': 'transformers', 'safetensors': 'safetensors',
           'huggingface_hub': 'huggingface_hub'}


def read(root, name):
    return json.loads(snapshots.contained(root, name).read_text(encoding='utf-8-sig'))


def requirements(root):
    """Read both checked-in lock lists rather than maintaining another version list."""
    expected = {}
    for name in ('requirements.txt', 'requirements-modeltools.txt'):
        for line in snapshots.contained(root, name).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith(('#', '--extra-index-url ')):
                continue
            match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)', line)
            if not match:
                raise ValueError('Unexpected unpinned requirement in ' + name)
            package, version = match.groups()
            if package in expected and expected[package] != version:
                raise ValueError('Conflicting requirement pin: ' + package)
            expected[package] = version
    if not expected:
        raise ValueError('Empty dependency pins.')
    return expected


def dependencies(root):
    records = []
    for package, pinned in requirements(root).items():
        try:
            actual = metadata.version(package)
        except metadata.PackageNotFoundError:
            actual = None
        module = MODULES.get(package, package.replace('-', '_'))
        available = util.find_spec(module) is not None
        records.append(dict(package=package, pinned=pinned, actual=actual,
                            module_present=available, passed=actual == pinned and available))
    if not all(row['passed'] for row in records):
        raise ValueError('Missing or mismatched dependencies: ' + ', '.join(
            row['package'] for row in records if not row['passed']))
    transitive = {name: util.find_spec(name) is not None for name in ('av', 'numpy', 'onnxruntime')}
    if not all(transitive.values()):
        raise ValueError('Missing transitive audio runtime modules.')
    return dict(packages=records, required_transitive_modules=transitive,
                transitive_dependencies_fully_locked=False, imports_executed=False, model_loads=0)


def release_models(root):
    catalog = read(root, 'config/releases/models-20261010.json')
    records = catalog['records']
    if len(records) != 2 or {row['kind'] for row in records} != {'stt', 'retrieval'}:
        raise ValueError('Expected exactly the STT and retrieval release records.')
    choice, stt_path = load_choice(root)  # Existing runtime weight/source checksum guard.
    if ((choice['source_repo'], choice['source_revision'], choice['model_sha256']) !=
            (PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256) or choice['decoding'] != EXPECTED_DECODING
            or (choice['device'], choice['compute_type']) != ('cpu', 'int8')):
        raise ValueError('Selected STT profile differs from the fixed runtime configuration.')
    result = []
    for record in records:
        validate_record(record)
        prefix = 'models/' + record['model_directory']
        weight = snapshots.contained(root, prefix + '/' + record['weight_file'])
        if snapshots.sha(weight) != record['model_sha256']:
            raise ValueError('Pinned model weight mismatch: ' + record['kind'])
        missing_notices = []
        for member in record['members']:
            if not snapshots.contained(root, member).is_file():
                # Original pre-release local model trees can lack the notices
                # included in the published ZIP. This does not stop inference,
                # but such a directory is not ready to redistribute as a bundle.
                if Path(member).name.startswith(('LICENSE-', 'REDISTRIBUTION-', 'UPSTREAM-MODEL-CARD')):
                    missing_notices.append(member)
                else:
                    raise ValueError('Missing model runtime member: ' + member)
        manifest = read(root, prefix + ('/download-manifest.json' if record['kind'] == 'stt'
                                        else '/source-manifest.json'))
        if (manifest['repo_id'], manifest['revision']) != (record['repo_id'], record['revision']):
            raise ValueError('Pinned model source mismatch: ' + record['kind'])
        for name, artifact in manifest['files'].items():
            path = snapshots.contained(root, prefix + '/' + name)
            if snapshots.sha(path) != artifact['sha256']:
                raise ValueError('Model runtime artifact mismatch: ' + prefix + '/' + name)
        if record['kind'] == 'stt' and (stt_path != weight.parent or
                choice['model_sha256'] != record['model_sha256']):
            raise ValueError('Selected STT differs from the release pin.')
        result.append(dict(kind=record['kind'], source=record['repo_id'], revision=record['revision'],
                           weight_sha256=record['model_sha256'], runtime_members=len(record['members']),
                           manifest_files_verified=len(manifest['files']),
                           distribution_notices_complete=not missing_notices,
                           missing_distribution_notices=missing_notices))
    return dict(records=result, full_sha256=True, inference_calls=0, downloaded=False)


def llm_files(root):
    config = read(root, 'runtime/rag-model.json')
    pin = read(root, 'config/model-catalog/gemma3-4b-text.json')
    if config['model'] != pin['local_model']:
        raise ValueError('Configured Gemma model differs from pinned catalog.')
    if _validated_base_url(config['base_url']) != 'http://127.0.0.1:11434':
        raise ValueError('Project launcher requires the default loopback-only Ollama origin.')
    name, tag = config['model'].split(':')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not re.fullmatch(r'[A-Za-z0-9_-]+', tag):
        raise ValueError('Unsupported local manifest name.')
    manifests = ['runtime/llm/models/' + directory + '/ollama.com/library/' + name + '/' + tag
                 for directory in ('manifests-v2', 'manifests')]
    manifest_path = next((value for value in manifests if (root / value).is_file()), None)
    if manifest_path is None:
        raise ValueError('Local Ollama model manifest is missing.')
    manifest = read(root, manifest_path)
    pinned = {row['mediaType']: (row['digest'], row['size']) for row in pin['layers']}
    actual = {row['mediaType']: (row['digest'], row['size']) for row in manifest['layers']}
    if len(actual) != len(manifest['layers']) or actual != pinned:
        raise ValueError('Local Gemma model layers differ from the pinned text-only model.')
    for row in [manifest['config'], *manifest['layers']]:
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest']):
            raise ValueError('Invalid model blob digest.')
        path = snapshots.contained(root, 'runtime/llm/models/blobs/' + row['digest'].replace(':', '-'))
        if path.stat().st_size != row['size'] or snapshots.sha(path) != row['digest'][7:]:
            raise ValueError('Local Gemma blob size or SHA256 mismatch.')
    binary = 'runtime/llm/ollama/' + ('ollama.exe' if os.name == 'nt' else 'ollama')
    if not snapshots.contained(root, binary).is_file():
        raise ValueError('Project-local Ollama executable is missing for this OS.')
    return dict(model=config['model'], layer_blobs_verified=len(manifest['layers']),
                full_sha256=True, provider_contacted=False, executable_present=True,
                executable_authenticity_checked=False)


def data_files(root):
    active = ContentReleaseManager(root).resolve()  # Fail closed on damaged active pointer/seal.
    data_root = Path(active['data_root']) if active else root
    for name in snapshots.DATABASES:
        snapshots.check_sqlite(snapshots.contained(data_root, name))
    paths, _ = snapshots.capture_integrity(data_root / snapshots.DATABASES[0], data_root, str(data_root))
    summary = snapshots.data_summary(data_root)
    if not ContentUsePolicy(root).enabled:
        raise ValueError('Official-source use policy is not configured.')
    return dict(mode='published' if active else 'legacy',
                release_id=active['release_id'] if active else None,
                capture_files_verified=len(paths), summary=summary,
                semantic_correctness_proven=False, database_writes=False)


def gateway_boundaries():
    allowed = [('GET', '/'), ('GET', '/api/status'), ('GET', '/demo/audio/q01.wav'),
               ('POST', '/api/voice/transcribe'), ('POST', '/api/route')]
    denied = [('GET', '/admin'), ('GET', '/admin.js'), ('GET', '/api/admin/state'),
              ('POST', '/api/admin/publish'), ('GET', '/api/voice/references'),
              ('GET', '/runtime/content.db'), ('GET', '/demo/audio/q04.wav'),
              ('GET', '/audio/q01.wav'), ('GET', '/api/voice/audio/not-an-owned-id'),
              ('GET', '/api/status?admin=true'), ('POST', '/api/reviews/stt')]
    if any(not allowed_path(*row) for row in allowed) or any(allowed_path(*row) for row in denied):
        raise ValueError('Public gateway route allowlist no longer preserves private boundaries.')
    return dict(allowed_route_probes=len(allowed), denied_route_probes=len(denied),
                implementation='tools.serve_device_demo.allowed_path', server_started=False,
                authentication_and_ingress_http_tested=False)


def check(root=ROOT):
    root = Path(root).resolve()
    checks = []
    def run(name, function):
        try:
            detail = function()
            checks.append(dict(name=name, passed=True, details=detail))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, sqlite3.Error) as error:
            checks.append(dict(name=name, passed=False, error_type=type(error).__name__, error=str(error)))
    run('python', lambda: python_profile())
    run('entrypoints', lambda: entrypoints(root))
    run('pinned_dependencies', lambda: dependencies(root))
    run('cafet_and_e5_files', lambda: release_models(root))
    run('gemma_and_ollama_files', lambda: llm_files(root))
    run('active_source_data', lambda: data_files(root))
    run('public_private_route_boundary', gateway_boundaries)
    model_check = next(row for row in checks if row['name'] == 'cafet_and_e5_files')
    notices_ready = (model_check['passed'] and all(row['distribution_notices_complete']
                     for row in model_check['details'].get('records', [])))
    return dict(schema_version=1, kind='nmct_offline_delivery_readiness',
        created_utc=datetime.now(timezone.utc).isoformat(),
        local_preflight_passed=all(row['passed'] for row in checks), checks=checks,
        model_distribution_notices_complete=notices_ready,
        stable_https_ready=False, stable_https_status='not_provisioned_or_verified_by_this_offline_check',
        external_delivery_requirements=[
            'Choose an always-on host with enough CPU/RAM/storage for the existing local model stack.',
            'Configure a stable public DNS name and browser-trusted TLS ingress with private admin excluded.',
            'Provision target access, persistent source/model storage, startup supervision, and backup restore.',
            'Verify online Edge TTS egress and actual microphone/playback on the final HTTPS origin.',
            'Repeat functional and isolation checks on the selected delivery machine; a Quick Tunnel is temporary.',
        ],
        checks_not_performed=['network requests', 'inference', 'model downloads', 'server/tunnel start',
            'provider authentication', 'TLS/DNS verification', 'clean-machine runtime installation',
            'human listening or answer scoring', 'load/availability benchmark'],
        modifications_performed=False)


def python_profile():
    if sys.version_info[:2] != (3, 11):
        raise ValueError('The pinned delivery environment was tested on Python 3.11.')
    return dict(version=platform.python_version(), platform=platform.system(),
                virtual_environment=sys.prefix != sys.base_prefix)


def entrypoints(root):
    missing = [name for name in ENTRYPOINTS if not snapshots.contained(root, name).is_file()]
    if missing:
        raise ValueError('Missing delivery entrypoints: ' + ', '.join(missing))
    return dict(files=len(ENTRYPOINTS), launch_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True, help='New private runtime JSON path; never overwritten.')
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to((args.root.resolve() / 'runtime').resolve()):
        parser.error('Save this machine-specific preflight inside the selected project runtime directory.')
    if destination.exists():
        parser.error('Output exists; choose a new output path.')
    result = check(args.root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(dict(output=str(destination), local_preflight_passed=result['local_preflight_passed'],
                          passed=sum(row['passed'] for row in result['checks']), total=len(result['checks']),
                          stable_https_ready=False), ensure_ascii=False))
    return 0 if result['local_preflight_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
