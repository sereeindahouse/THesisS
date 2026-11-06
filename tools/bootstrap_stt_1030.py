"""10/30-ны Whisper (Cafet) ба Gemini-ийн 12 хос бичлэгт paired bootstrap 95% интервал.

Хадгалсан `combined-summary.json`-ийн бичлэг бүрийн WER ба manifest-ийн reference-ийн
үгийн тоог л уншина (текст хэвлэхгүй, сүлжээ 0). Дипломын 4-р бүлгийн тоо.

    .venv/Scripts/python.exe tools/bootstrap_stt_1030.py
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runtime/stt-candidate-20261030'
SEED, ROUNDS = 20261106, 10000


def words(text):
    text = unicodedata.normalize('NFC', text).casefold()
    return re.sub(r'[^\w\s]', ' ', text).split()


def paired_rows():
    summary = json.loads((RUN / 'combined-summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((RUN / 'paired-first-free/manifest-snapshot.json').read_text(encoding='utf-8'))
    length = {row['id']: len(words(row['reference'])) for row in manifest['human_rows']}
    whisper = {row['id']: row['wer'] for row in summary['baseline']['rows']}
    gemini = {row['id']: row['wer'] for row in summary['candidate']['rows']}
    rows = {}
    for key in whisper:
        n = length[key]
        rows[key] = (n, round(whisper[key] * n), round(gemini[key] * n))
        assert abs(whisper[key] * n - rows[key][1]) < 1e-6 and abs(gemini[key] * n - rows[key][2]) < 1e-6, key
    totals = [sum(row[i] for row in rows.values()) for i in range(3)]
    assert totals == [summary['baseline']['reference_words'], summary['baseline']['word_edit_errors'],
                      summary['candidate']['word_edit_errors']], totals
    return rows


def bootstrap(rows):
    keys = list(rows)
    rng = random.Random(SEED)
    whisper, gemini, diff = [], [], []
    for _ in range(ROUNDS):
        sample = [rows[rng.choice(keys)] for _ in keys]
        n = sum(row[0] for row in sample)
        whisper.append(sum(row[1] for row in sample) / n)
        gemini.append(sum(row[2] for row in sample) / n)
        diff.append(gemini[-1] - whisper[-1])
    ci = lambda values: [round(sorted(values)[int(ROUNDS * q)] * 100, 1) for q in (0.025, 0.975)]
    return {
        'pairs': len(keys), 'words': sum(row[0] for row in rows.values()),
        'whisper_wer_ci95': ci(whisper), 'gemini_wer_ci95': ci(gemini), 'gemini_minus_whisper_pp_ci95': ci(diff),
        'gemini_better': sum(rows[k][2] < rows[k][1] for k in keys),
        'gemini_worse': sum(rows[k][2] > rows[k][1] for k in keys),
        'seed': SEED, 'rounds': ROUNDS,
    }


if __name__ == '__main__':
    print(json.dumps(bootstrap(paired_rows()), ensure_ascii=False, indent=1))
