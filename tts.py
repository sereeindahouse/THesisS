"""Online Edge TTS experiment; it is not an offline or production service guarantee."""
import argparse
import asyncio
import json
import time
from pathlib import Path

async def run(a):
    import edge_tts
    output = Path(a.output)
    timing = output.with_suffix('.timing.json')
    if output.exists() or timing.exists():
        raise SystemExit('Output exists. Choose a new filename for this run.')
    text = Path(a.text_file).read_text(encoding='utf-8-sig').strip()
    if not text:
        raise SystemExit('Text file is empty.')
    voices = await edge_tts.list_voices()
    if a.voice not in {v['ShortName'] for v in voices}:
        raise SystemExit('Requested voice is not currently available in the service.')
    output.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    await edge_tts.Communicate(text, a.voice).save(str(output))
    elapsed = time.perf_counter() - start
    timing.write_text(json.dumps({'voice': a.voice, 'characters': len(text),
                                 'synthesis_seconds': elapsed,
                                 'service': 'online Edge TTS experiment'}, indent=2), encoding='utf-8')
    print(f'Saved: {output}; synthesis {elapsed:.2f}s (voice-list request excluded)')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--text-file', default='data/tts-text.txt')
    p.add_argument('--voice', default='mn-MN-YesuiNeural')
    p.add_argument('--output', default='results/tts01.mp3')
    asyncio.run(run(p.parse_args()))

if __name__ == '__main__':
    main()
