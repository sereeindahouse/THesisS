"""Score manually verified reference/hypothesis pairs; never use fabricated results."""
import argparse
import json
import sys
import unicodedata
from pathlib import Path

def normalize(text):
    text = unicodedata.normalize('NFC', text).casefold()
    # Punctuation becomes space; numbers are not rewritten in this baseline.
    text = ''.join(' ' if unicodedata.category(c).startswith('P') else c for c in text)
    return ' '.join(text.split())

def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[j-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = new
    return row[-1]

def score(pairs):
    words = characters = word_errors = character_errors = exact = 0
    rows = []
    for pair in pairs:
        ref, hyp = normalize(pair['reference']), normalize(pair['hypothesis'])
        if not ref:
            raise ValueError('Reference must not be empty; use separate silence tests.')
        rw, hw = ref.split(), hyp.split()
        rc, hc = ref.replace(' ', ''), hyp.replace(' ', '')
        we, ce = distance(rw, hw), distance(rc, hc)
        words += len(rw); characters += len(rc)
        word_errors += we; character_errors += ce; exact += ref == hyp
        rows.append({'id': pair['id'], 'wer': we / len(rw), 'cer': ce / len(rc)})
    if not pairs:
        raise ValueError('No pairs supplied.')
    return {'normalization': 'NFC + casefold + punctuation to spaces; CER excludes spaces; numbers unchanged',
            'utterances': len(pairs), 'reference_words': words,
            'reference_characters': characters, 'word_edit_errors': word_errors,
            'character_edit_errors': character_errors, 'corpus_wer': word_errors / words,
            'corpus_cer': character_errors / characters,
            'normalized_sentence_exact_match': exact / len(pairs), 'rows': rows}

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('pairs')
    p.add_argument('--output', default='results/metrics.json')
    a = p.parse_args()
    output = Path(a.output)
    if output.exists():
        p.error('Output exists. Choose a new filename.')
    result = score(json.loads(Path(a.pairs).read_text(encoding='utf-8-sig')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"WER: {result['corpus_wer']:.1%}; CER: {result['corpus_cer']:.1%}")
    print('Saved:', output)

if __name__ == '__main__':
    main()
