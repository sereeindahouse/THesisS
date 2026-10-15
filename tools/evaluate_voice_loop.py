"""Synthetic Mongolian voice integration experiment; never human ASR gold.

Question TTS -> WAV -> actual demo STT -> typed/raw RAG -> bound answer TTS.
All audio/transcripts stay in a new private directory. No weights are trained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def audio_duration(data):
    import av
    with av.open(io.BytesIO(data),format='mp3') as stream:
        return sum(frame.samples/frame.sample_rate for frame in stream.decode(audio=0))


def contract_check(case, response):
    """A transparent smoke check, not an answer correctness evaluator."""
    import re
    text=response.get('answer') or response.get('message','')
    return dict(route_matches=response.get('route') in case['expected_routes'],
                field_patterns_present=all(re.search(p,text,re.I) for p in case['required_patterns']),
                correctness_certified=False, human_review=None)


def run(cases_path,output_dir,base_url,reuse_audio=None):
    from voice_runtime import VoiceRuntime, ALLOWED_VOICES, _decode_pcm, _wav_bytes
    from score import score
    from tools.evaluate_answer_quality import RUNTIME_ARTIFACT_NAMES, sha as file_sha
    parts=urlsplit(base_url)
    if (parts.scheme!='http' or parts.hostname not in {'127.0.0.1','localhost'}
            or parts.username or parts.password or parts.path not in {'','/'} or parts.query or parts.fragment):
        raise ValueError('Use the loopback demo only.')
    bundle=json.loads(cases_path.read_text(encoding='utf-8-sig'))
    cases=bundle['cases']
    if not 1<=len(cases)<=12 or bundle.get('synthetic_voice') is not True:
        raise ValueError('Use 1–12 explicitly synthetic development questions.')
    if len({c['id'] for c in cases})!=len(cases):
        raise ValueError('Question IDs must be unique.')
    for case in cases:
        if (not case.get('query') or len(case['query'])>250 or case.get('label_author')!='assistant'
                or case.get('human_reference_review') is not False or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',case['id'])):
            raise ValueError('Short questions and honest assistant reference labels required.')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path,payload=None,content_type='application/json',binary=False):
        data=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
        req=urllib.request.Request(base_url.rstrip('/')+path,data=data,
            headers={'Origin':base_url.rstrip('/'),'Content-Type':content_type})
        with opener.open(req,timeout=180) as response:
            return response.read() if binary else json.load(response)

    names=RUNTIME_ARTIFACT_NAMES
    expected={n:file_sha(ROOT/n) for n in names}
    if any(value is None for value in expected.values()):
        raise ValueError('Runtime fingerprint requires all required local code files.')
    status=request('/api/status')
    if any(status.get('rag',{}).get('loaded_artifact_sha256',{}).get(n)!=v for n,v in expected.items()):
        raise ValueError('Stale demo code; restart before voice collection.')
    if status.get('voice',{}).get('stt_ready') is not True:
        raise ValueError('Local STT dependencies/model are missing; use the existing project setup before voice collection.')
    previous=None
    if reuse_audio is not None:
        previous=json.loads((reuse_audio/'results.json').read_text(encoding='utf-8'))
        if previous['cases_sha256']!=file_sha(cases_path) or previous.get('synthetic_voice') is not True:
            raise ValueError('Replay requires the same synthetic questions.')
    output_dir.mkdir(parents=True,exist_ok=False)
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        cases_sha256=file_sha(cases_path),source_snapshot_sha256=bundle['source_snapshot_sha256'],
        experiment='synthetic TTS audio -> local STT -> typed/raw RAG -> response-bound TTS',
        synthetic_voice=True,human_voice=False,human_answer_review=False,human_listening_quality=False,
        independent_held_out_evaluation=False,own_training=False,
        reuse_audio_from=str(reuse_audio) if reuse_audio else None,
        previous_run_sha256=file_sha(reuse_audio/'results.json') if reuse_audio else None,
        runtime_preflight=dict(status=status,matched=True,expected_artifact_sha256=expected),
        artifact_sha256={n:file_sha(ROOT/n) for n in (*names,'voice_runtime.py','tools/evaluate_voice_loop.py','score.py')},
        warnings=['Synthetic TTS is not a natural speaker/noise/device benchmark.',
                  'WER/CER compare input TTS text to raw STT; numbers unchanged.',
                  'Pattern/route smoke checks do not prove semantic correctness.'],cases=[])
    output=output_dir/'results.json'

    def save():
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

    save()
    question_tts=VoiceRuntime(ROOT) if previous is None else None
    for voice in ALLOWED_VOICES:
        for case in cases:
            start=time.perf_counter()
            stem=case['id']+'-'+('bataa' if 'Bataa' in voice else 'yesui')
            row=dict(case,voice=voice,synthetic_voice=True,human_review=None)
            report['cases'].append(row)
            try:
                if previous is None:
                    spoken=question_tts.synthesize(case['query'],voice)
                    mp3,_=question_tts.audio(spoken['id'])
                    pcm=_decode_pcm(mp3,'mp3');wav=_wav_bytes(pcm)
                else:
                    old=next(c for c in previous['cases'] if c['id']==case['id'] and c['voice']==voice)
                    mp3=(reuse_audio/(stem+'-question.mp3')).read_bytes()
                    wav=(reuse_audio/(stem+'-question.wav')).read_bytes()
                    if (old['query']!=case['query'] or sha(mp3)!=old['input_mp3_sha256']
                            or sha(wav)!=old['input_wav_sha256']):
                        raise ValueError('Replay audio changed; keep previous artifacts intact.')
                    spoken=old['question_tts'];row['reused_question_audio']=True
                (output_dir/(stem+'-question.mp3')).write_bytes(mp3)
                # Generated MP3 is converted locally; untrusted HTTP uploads still
                # use the demo's normal bounded WAV decoder and STT configuration.
                (output_dir/(stem+'-question.wav')).write_bytes(wav)
                row.update(question_tts=spoken,input_mp3_sha256=sha(mp3),input_wav_sha256=sha(wav))
                row['transcription']=request('/api/voice/transcribe',wav,'audio/wav')
                raw=row['transcription']['text']
                row['raw_stt']=raw
                row['synthetic_text_score']=score([dict(id=stem,reference=case['query'],hypothesis=raw)])
                row['typed_response']=request('/api/route',dict(query=case['query'],allow_draft=False))
                row['typed_smoke']=contract_check(case,row['typed_response'])
                if not raw.strip():
                    raise ValueError('STT returned empty text.')
                response=request('/api/route',dict(query=raw,allow_draft=False))
                row['raw_response']=response
                row['raw_smoke']=contract_check(case,response)
                row['answer_tts']=request('/api/voice/speak',dict(query=raw,
                    allow_draft=False,voice=voice,package_id=response['package_id'],response_id=response['response_id']))
                sound=request(row['answer_tts']['audio_url'],binary=True)
                (output_dir/(stem+'-answer.mp3')).write_bytes(sound)
                row.update(answer_audio_sha256=sha(sound),answer_audio_seconds=audio_duration(sound),
                           answer_audio_decoded=True)
            except Exception as error:
                row.update(error=type(error).__name__+': '+str(error))
                if isinstance(error,urllib.error.HTTPError):
                    try:row['http_error_body']=json.loads(error.read())
                    except Exception:pass
            row['wall_seconds']=round(time.perf_counter()-start,3)
            save()
            print(stem,row.get('raw_stt'),row.get('raw_response',{}).get('route'),row.get('error',''),flush=True)
    pairs=[dict(id=c['id']+'-'+c['voice'],reference=c['query'],hypothesis=c['raw_stt']) for c in report['cases'] if 'raw_stt' in c]
    report['synthetic_text_score']=score(pairs) if pairs else None
    report['completed_clips']=sum(c.get('answer_audio_decoded',False) for c in report['cases'])
    save()
    from tools.voice_report import write_report
    write_report(output)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'data/voice-loop-dev-20261014.json')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--reuse-audio',type=Path,help='Replay byte-identical question audio from an earlier private run.')
    parser.add_argument('--render-report',type=Path,help='Render an existing private results.json without model/network calls.')
    parser.add_argument('--open-report',action='store_true',help='Open the local HTML report in the default browser.')
    parser.add_argument('--refresh-view',action='store_true',help='Replace derived HTML only when rendering an existing results.json.')
    args=parser.parse_args()
    if args.render_report:
        from tools.voice_report import write_report
        report=write_report(args.render_report,replace=args.refresh_view)
    else:
        folder=args.output_dir or ROOT/'runtime'/('voice-selftest-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        result=run(args.cases,folder,args.base_url,args.reuse_audio)
        report=folder/'index.html'
        print('Private report:',report)
        print('Decoded answer audio:',result['completed_clips'],'/',len(result['cases']))
    if args.open_report:
        import webbrowser
        webbrowser.open(report.resolve().as_uri())
    if not args.render_report and result['completed_clips']!=len(result['cases']):
        raise SystemExit(1)
