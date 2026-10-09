"""Convert verified Mongolian Whisper weights with the official CT2 converter."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4*1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='whisper-small-mn-cafet-hf')
    parser.add_argument('--output', default='faster-whisper-small-mn-cafet')
    args = parser.parse_args()
    source, output = ROOT/'models'/args.source, ROOT/'models'/args.output
    model_root = (ROOT/'models').resolve()
    if any(not path.resolve().is_relative_to(model_root) or path.resolve() == model_root for path in (source, output)):
        parser.error('Source and output must be subdirectories of models.')
    metadata = json.loads((source/'source-manifest.json').read_text(encoding='utf-8'))
    assert digest(source/'model.safetensors') == metadata['files']['model.safetensors']['sha256']
    assert not output.exists(), 'Never overwrite an existing converted model.'
    compatible = source.with_name(source.name + '-compat')
    compatible.mkdir(exist_ok=True)
    assert compatible.resolve().is_relative_to((ROOT/'models').resolve())
    for path in source.iterdir():
        if not path.is_file() or path.name in ('source-manifest.json', 'active-download.lock'):
            continue
        target = compatible/path.name
        if path.name == 'model.safetensors':
            if not target.exists():
                os.link(path, target)
        else:
            shutil.copy2(path, target)
    tokenizer_config = json.loads((compatible/'tokenizer_config.json').read_text(encoding='utf-8'))
    adaptations = []
    if isinstance(tokenizer_config.get('extra_special_tokens'), list):
        tokenizer_config['additional_special_tokens'] = tokenizer_config.pop('extra_special_tokens')
        (compatible/'tokenizer_config.json').write_text(json.dumps(tokenizer_config, ensure_ascii=False, indent=2), encoding='utf-8')
        adaptations.append('Transformers 5 list extra_special_tokens renamed to legacy additional_special_tokens; tokenizer.json and IDs unchanged.')
    combined_path = compatible/'processor_config.json'
    if combined_path.exists() and not (compatible/'preprocessor_config.json').exists():
        combined = json.loads(combined_path.read_text(encoding='utf-8'))
        features = combined.get('feature_extractor')
        assert isinstance(features, dict) and features.get('sampling_rate') == 16000
        (compatible/'preprocessor_config.json').write_text(json.dumps(features, indent=2), encoding='utf-8')
        adaptations.append('Nested feature extractor copied to the legacy preprocessor_config.json location without changing parameters.')
    assert digest(compatible/'model.safetensors') == metadata['files']['model.safetensors']['sha256']
    if 'tokenizer.json' in metadata['files']:
        assert digest(compatible/'tokenizer.json') == metadata['files']['tokenizer.json']['sha256']
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from ctranslate2.converters import TransformersConverter
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(compatible), local_files_only=True, trust_remote_code=False)
    if not (compatible/'tokenizer.json').exists():
        assert hasattr(tokenizer, 'backend_tokenizer'), 'A fast tokenizer is required for the local runtime.'
        tokenizer.backend_tokenizer.save(str(compatible/'tokenizer.json'))
        adaptations.append('Fast tokenizer.json serialized from the checkpoint vocab.json and merges.txt; special token IDs verified.')
    generation = json.loads((compatible/'generation_config.json').read_text(encoding='utf-8'))
    token_ids = {
        '<|mn|>': generation.get('lang_to_id',{}).get('<|mn|>',50314),
        '<|startoftranscript|>': generation['decoder_start_token_id'],
        '<|notimestamps|>': generation['no_timestamps_token_id']}
    for token,identity in token_ids.items():
        assert tokenizer.convert_tokens_to_ids(token) == identity, f'Unexpected special token ID: {token}'
    started = time.monotonic()
    print(f'Converting verified weights locally: {source.name}; no training.', flush=True)
    converter = TransformersConverter(str(compatible), trust_remote_code=False,
                                     copy_files=['tokenizer.json', 'generation_config.json', 'preprocessor_config.json'])
    converter.convert(str(output), quantization='float16')
    # New Transformers 5 checkpoints put the feature extractor inside processor_config.
    preprocessor = compatible/'preprocessor_config.json'
    if preprocessor.exists():
        shutil.copy2(preprocessor, output/preprocessor.name)
    elif (source/'processor_config.json').exists():
        combined = json.loads((source/'processor_config.json').read_text(encoding='utf-8'))
        features = combined.get('feature_extractor')
        assert isinstance(features, dict) and features.get('sampling_rate') == 16000
        (output/'preprocessor_config.json').write_text(json.dumps(features, indent=2), encoding='utf-8')
    elapsed = time.monotonic()-started
    manifest = dict(repo_id=metadata['repo_id'], revision=metadata['revision'],
        license=metadata['license'], source_model=metadata['repo_id'],
        source_manifest=str(source/'source-manifest.json'),
        source_weight_sha256=metadata['files']['model.safetensors']['sha256'],
        conversion=dict(tool='ctranslate2.converters.TransformersConverter', trust_remote_code=False,
                        quantization='float16', training_performed=False, seconds=elapsed,
                        compatibility_adaptations=adaptations, token_ids_verified=True, verified_token_ids=token_ids,
                        versions={name:importlib.metadata.version(name) for name in ('torch','transformers','ctranslate2','safetensors')}),
        created_at=datetime.now(timezone.utc).isoformat(), audio_upload=False,
        files={path.name:dict(size=path.stat().st_size, sha256=digest(path)) for path in output.iterdir() if path.is_file()})
    (output/'download-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Verified converted model ready: {output}, conversion {elapsed:.2f}s.', flush=True)


if __name__ == '__main__':
    main()
