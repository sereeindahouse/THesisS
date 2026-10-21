"""Paired constructed speech-formatting checks; no ASR accuracy or MOS claims.

Offline by default. --synthesize explicitly sends only the built-in constructed
texts to the existing online Edge voices, saves before/after MP3s and decodes
them. Human listening fields remain empty. An optional baseline must contain
these exact built-in rows and the output of a separately frozen earlier module.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from speech_text import normalize_spoken_currency, normalize_spoken_notation

CASES = (
    ('year2026', 'calendar_year', '2026 оны элсэлт.', {'year': '2026'},
     'хоёр мянга хорин зургаан оны элсэлт.'),
    ('year2000', 'calendar_year', '2000 онд байгуулагдсан.', {'year': '2000'},
     'хоёр мянган онд байгуулагдсан.'),
    ('year2021', 'calendar_year', '2021 оны мэдээлэл.', {'year': '2021'},
     'хоёр мянга хорин нэгэн оны мэдээлэл.'),
    ('phone', 'labelled_phone', 'Утас: 00112233.', {'phone': '00112233'},
     'Утас: тэг тэг нэг нэг, хоёр хоёр гурав гурав.'),
    ('phone_upper', 'labelled_phone', 'ХОЛБОО БАРИХ УТАСНЫ ДУГААР: 77123456.',
     {'phone': '77123456'},
     'ХОЛБОО БАРИХ УТАСНЫ ДУГААР: долоо долоо нэг хоёр, гурав дөрөв тав зургаа.'),
    ('combined', 'calendar_year_and_phone', '2026 оны Сора тэтгэлэг биш. Утас: 77123456.',
     {'year': '2026', 'phone': '77123456', 'name': 'Сора', 'negation': 'биш'},
     'хоёр мянга хорин зургаан оны Сора тэтгэлэг биш. '
     'Утас: долоо долоо нэг хоёр, гурав дөрөв тав зургаа.'),
    ('currency_qr', 'existing_currency_qr', 'QR кодоор 20,000 төгрөг төлнө.',
     {'amount': '20000', 'unit': 'төгрөг'}, 'кью ар кодоор хорин мянган төгрөг төлнө.'),
    ('date', 'unchanged_control', '2026-10-20, 2026 оны 10-р сарын 20.', {},
     '2026-10-20, 2026 оны 10-р сарын 20.'),
    ('range', 'unchanged_control', '2025 – 2026 оны журам. Утас: 77123456 - 88123456.', {},
     '2025 – 2026 оны журам. Утас: 77123456 - 88123456.'),
    ('codes', 'unchanged_control', 'QR-2026, M2026 оны код, 20.26, 77123456.', {},
     'QR-2026, M2026 оны код, 20.26, 77123456.'),
    ('international', 'unchanged_control', 'Утас: +976 77123456; утас: 7017-2794.', {},
     'Утас: +976 77123456; утас: 7017-2794.'),
    ('unlabelled', 'unchanged_control', 'Батаа, Есүй, 77123456, 2099, 1999 оны эх.', {},
     'Батаа, Есүй, 77123456, 2099, 1999 оны эх.'),
)
VOICES = {'bataa': 'mn-MN-BataaNeural', 'yesui': 'mn-MN-YesuiNeural'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def critical_values_check(spoken, critical):
    """Independent small inverse parser for the constructed year/phone cases."""
    checks = {}
    if 'year' in critical:
        values = {'нэгэн': 1, 'хоёр': 2, 'гурван': 3, 'дөрвөн': 4, 'таван': 5,
                  'зургаан': 6, 'долоон': 7, 'найман': 8, 'есөн': 9,
                  'арван': 10, 'хорин': 20, 'гучин': 30, 'дөчин': 40, 'тавин': 50,
                  'жаран': 60, 'далан': 70, 'наян': 80, 'ерэн': 90}
        match = re.search(r'хоёр мянг(?:а|ан)(?P<tail>(?: [а-яөүё]+)*?) (?:он|оны|онд)\b', spoken)
        words = match['tail'].split() if match else []
        checks['calendar_year_value_preserved'] = bool(match) and all(w in values for w in words) and (
            2000 + sum(values.get(w, 0) for w in words) == int(critical['year']))
    if 'phone' in critical:
        digits = dict(zip('тэг нэг хоёр гурав дөрөв тав зургаа долоо найм ес'.split(), '0123456789'))
        match = re.search(r'утас(?:ны\s+дугаар)?\s*:?\s*([^.!?]+)', spoken, re.I)
        words = re.findall(r'\w+', match[1]) if match else []
        recovered = ''.join(digits.get(word, '?') for word in words)
        checks['phone_eight_digits_and_order_preserved'] = recovered == critical['phone']
    for field in ('name', 'negation', 'unit'):
        if field in critical:
            checks[field + '_preserved'] = critical[field] in spoken
    if 'amount' in critical:
        # The built-in corpus has one already-supported amount; do not imply a
        # general parser or certify unrelated currency morphology.
        checks['known_currency_value_preserved'] = critical['amount'] == '20000' and 'хорин мянган төгрөг' in spoken
    return checks


def _read_baseline(path):
    if path is None:
        return None
    baseline = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = baseline.get('cases')
    if baseline.get('constructed') is not True or not isinstance(rows, list) or len(rows) != len(CASES):
        raise ValueError('The baseline must contain the twelve unchanged constructed cases.')
    expected = {row[0]: row for row in CASES}
    if {row.get('id') for row in rows} != set(expected):
        raise ValueError('Baseline case IDs changed.')
    for row in rows:
        wanted = expected[row['id']]
        if (row.get('written') != wanted[2] or row.get('critical_values') != wanted[3]
                or row.get('type') != wanted[1]
                or row.get('source') != 'assistant_constructed_not_school_fact'
                or row.get('spoken_before') != (wanted[4] if wanted[0] == 'currency_qr' else wanted[2])):
            raise ValueError('Baseline constructed texts, types or values changed.')
    return {row['id']: row for row in rows}


def _synthesize(text, voice, destination):
    from voice_runtime import _edge_audio, TTS_TIMEOUT_SECONDS
    import av
    started = time.perf_counter()

    async def limited():
        return await asyncio.wait_for(_edge_audio(text, voice), TTS_TIMEOUT_SECONDS)

    audio = asyncio.run(limited())
    elapsed = time.perf_counter() - started
    destination.write_bytes(audio)
    with av.open(io.BytesIO(audio), format='mp3') as stream:
        duration = sum(frame.samples / frame.sample_rate for frame in stream.decode(audio=0))
    if duration <= 0:
        raise ValueError('The provider audio decoded to no samples.')
    return dict(path=destination.name, sha256=sha(audio), bytes=len(audio), decoded_seconds=duration,
                synthesis_seconds=elapsed, provider_request=True, exact_provider_text=text,
                human_quality_accepted=None)


def evaluate(output_dir, *, baseline_path=None, synthesize=False, voice_names=('bataa', 'yesui'), case_ids=None):
    baseline = _read_baseline(baseline_path)
    selected = set(case_ids) if case_ids is not None else {case[0] for case in CASES}
    if not selected or not selected <= {case[0] for case in CASES}:
        raise ValueError('Select built-in constructed case IDs only.')
    if not voice_names or any(v not in VOICES for v in voice_names):
        raise ValueError('Choose the existing Bataa/Yesui voices.')
    if synthesize and baseline is None:
        raise ValueError('Paired audio requires an exact separately frozen baseline.')
    output_dir.mkdir(parents=True, exist_ok=False)
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                  experiment='constructed written-to-spoken value-preservation and optional paired audio',
                  constructed=True, school_facts=False, private_audio_used=False,
                  baseline_sha256=sha(baseline_path.read_bytes()) if baseline_path else None,
                  speech_text_sha256=sha((ROOT / 'speech_text.py').read_bytes()),
                  evaluator_sha256=sha(Path(__file__).read_bytes()),
                  raw_stt_quality_measured=False, listening_quality_measured=False,
                  human_listening=None, mos=None, training_performed=False,
                  synthesis_requested=synthesize, provider_requests=0, cases=[])
    destination = output_dir / 'results.json'

    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    for cid, kind, written, critical, expected in CASES:
        if cid not in selected:
            continue
        spoken = normalize_spoken_currency(normalize_spoken_notation(written))
        checks = critical_values_check(spoken, critical)
        checks['exact_constructed_expected_text'] = spoken == expected
        checks['idempotent'] = normalize_spoken_currency(normalize_spoken_notation(spoken)) == spoken
        if kind == 'unchanged_control':
            checks['ambiguous_or_outside_scope_untouched'] = spoken == written
        before = baseline[cid]['spoken_before'] if baseline else None
        row = dict(id=cid, type=kind, source='assistant_constructed_not_school_fact',
                   written=written, spoken_before=before, spoken_after=spoken,
                   expected_spoken_constructed=expected, critical_values=critical,
                   changed_from_frozen_baseline=(spoken != before) if baseline else None,
                   checks=checks, human_heard_critical_values=None, human_listening_rating=None,
                   audio=[])
        report['cases'].append(row)
        save()
        if synthesize:
            for voice_name in voice_names:
                for variant, provider_text in (('before', before), ('after', spoken)):
                    audio_row = dict(voice=VOICES[voice_name], variant=variant)
                    row['audio'].append(audio_row)
                    report['provider_requests'] += 1
                    try:
                        audio_row.update(_synthesize(provider_text, VOICES[voice_name],
                            output_dir / f'{cid}-{voice_name}-{variant}.mp3'))
                        audio_row['success'] = True
                    except Exception as exc:
                        audio_row.update(success=False, error_type=type(exc).__name__)
                    save()
    report['summary'] = dict(cases=len(report['cases']),
        deterministic_checks_passed=sum(all(row['checks'].values()) for row in report['cases']),
        changed_cases=sum(row['changed_from_frozen_baseline'] is True for row in report['cases']),
        audio_decodes_passed=sum(a.get('success') is True for r in report['cases'] for a in r['audio']),
        provider_attempts=report['provider_requests'],
        not_an_asr_accuracy_or_human_listening_score=True)
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--synthesize', action='store_true',
                        help='Send the built-in constructed before/after text to online Edge TTS.')
    parser.add_argument('--voices', nargs='+', choices=tuple(VOICES), default=['bataa', 'yesui'])
    parser.add_argument('--case-ids', nargs='+', choices=tuple(row[0] for row in CASES))
    args = parser.parse_args()
    report = evaluate(args.output_dir, baseline_path=args.baseline, synthesize=args.synthesize,
                      voice_names=tuple(dict.fromkeys(args.voices)), case_ids=args.case_ids)
    print(json.dumps(report['summary'], ensure_ascii=False))
    return 0 if report['summary']['deterministic_checks_passed'] == report['summary']['cases'] and (
        not args.synthesize or report['summary']['audio_decodes_passed'] == report['summary']['provider_attempts']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
