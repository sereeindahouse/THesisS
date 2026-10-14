import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import evaluate_voice_loop as loop


class SyntheticLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.cases=self.root/'cases.json';self.output=self.root/'out'
        self.bundle=dict(synthetic_voice=True,source_snapshot_sha256='frozen',cases=[dict(
            id='one',query='Бичгийн шалгалтын нийт оноо хэд вэ?',expected_routes=['A'],
            required_patterns=['100'],label_author='assistant',human_reference_review=False)])
        self.cases.write_text(json.dumps(self.bundle),encoding='utf-8')

    def test_remote_url_cannot_receive_generated_audio(self):
        with patch.object(loop.urllib.request,'build_opener') as network:
            with self.assertRaises(ValueError):loop.run(self.cases,self.output,'http://example.com')
            network.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_non_synthetic_bundle_rejected_before_network_or_output(self):
        self.bundle['synthetic_voice']=False
        self.cases.write_text(json.dumps(self.bundle),encoding='utf-8')
        with patch.object(loop.urllib.request,'build_opener') as network:
            with self.assertRaises(ValueError):loop.run(self.cases,self.output,'http://127.0.0.1:8765')
            network.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_raw_recognition_is_forwarded_and_answer_voice_is_bound_to_raw_response(self):
        calls=[];synthesized=[]
        hashes={n:hashlib.sha256((loop.ROOT/n).read_bytes()).hexdigest()
                for n in ('rag_runtime.py','source_fields.py','answer_contract.py')}
        raw='Өөрөөр таньсан текст'
        class Opener:
            def open(self,req,timeout):
                path=req.full_url.split(':8765')[-1]
                if path=='/api/status':value=dict(rag=dict(loaded_artifact_sha256=hashes),voice=dict(stt_ready=True))
                elif path=='/api/voice/transcribe':
                    self_payload=req.data;calls.append((path,self_payload,req.get_header('Content-type')))
                    value=dict(text=raw)
                elif path=='/api/route':
                    body=json.loads(req.data);calls.append((path,body))
                    typed=body['query']!=raw
                    value=dict(route='A' if typed else 'E',answer='100 оноо' if typed else None,
                        message='Мэдээлэл олдсонгүй',response_id='typed-id' if typed else 'raw-id',package_id='pkg')
                elif path=='/api/voice/speak':
                    body=json.loads(req.data);calls.append((path,body));value=dict(audio_url='/api/voice/audio/answer')
                elif path=='/api/voice/audio/answer':return io.BytesIO(b'mp3answer')
                else:raise AssertionError(path)
                return io.BytesIO(json.dumps(value).encode())
        class TTS:
            def __init__(self,root):pass
            def synthesize(self,text,voice):synthesized.append(text);return dict(id='question')
            def audio(self,identifier):return b'mp3question','audio/mpeg'
        with patch.object(loop.urllib.request,'build_opener',return_value=Opener()), \
                patch('voice_runtime.VoiceRuntime',TTS),patch('voice_runtime._decode_pcm',return_value=b'pcm'), \
                patch('voice_runtime._wav_bytes',return_value=b'WAV'),patch.object(loop,'audio_duration',return_value=2.5):
            result=loop.run(self.cases,self.output,'http://127.0.0.1:8765')
            replay=loop.run(self.cases,self.root/'replay','http://127.0.0.1:8765',self.output)
        self.assertEqual(result['completed_clips'],2)
        self.assertTrue(result['synthetic_voice']);self.assertFalse(result['human_voice'])
        self.assertFalse(result['own_training']);self.assertFalse(result['human_answer_review'])
        self.assertEqual(synthesized,[self.bundle['cases'][0]['query']]*2)
        self.assertTrue(all(r.get('reused_question_audio') for r in replay['cases']))
        self.assertEqual([r['input_wav_sha256'] for r in result['cases']],[r['input_wav_sha256'] for r in replay['cases']])
        for row in result['cases']:
            self.assertEqual(row['raw_stt'],raw)
            self.assertTrue(row['typed_smoke']['route_matches'])
            self.assertFalse(row['raw_smoke']['route_matches'])
            self.assertFalse(row['raw_smoke']['correctness_certified'])
            self.assertIsNone(row['human_review'])
        for path,*detail in calls:
            if path=='/api/voice/transcribe':self.assertEqual(detail,[b'WAV','audio/wav'])
            if path=='/api/voice/speak':
                self.assertEqual(detail[0]['query'],raw)
                self.assertEqual(detail[0]['response_id'],'raw-id')
        original=(self.output/'results.json').read_bytes()
        with patch.object(loop.urllib.request,'build_opener',return_value=Opener()):
            with self.assertRaises(FileExistsError):loop.run(self.cases,self.output,'http://127.0.0.1:8765')
        self.assertEqual((self.output/'results.json').read_bytes(),original)

    def test_missing_local_stt_blocks_question_tts_and_output(self):
        hashes={n:hashlib.sha256((loop.ROOT/n).read_bytes()).hexdigest()
                for n in ('rag_runtime.py','source_fields.py','answer_contract.py')}
        class Opener:
            def open(self,req,timeout):
                self_path=req.full_url.split(':8765')[-1]
                if self_path!='/api/status':raise AssertionError('Audio/question request before readiness')
                return io.BytesIO(json.dumps(dict(rag=dict(loaded_artifact_sha256=hashes),voice=dict(stt_ready=False))).encode())
        with patch.object(loop.urllib.request,'build_opener',return_value=Opener()),patch('voice_runtime.VoiceRuntime') as tts:
            with self.assertRaises(ValueError):loop.run(self.cases,self.output,'http://127.0.0.1:8765')
            tts.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
