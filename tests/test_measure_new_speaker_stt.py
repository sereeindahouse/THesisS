"""Constructed PCM/test text only. No microphone, real people, API or key access."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
import re
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import wave

import tools.measure_new_speaker_stt as study


def fake_wav(value=100, seconds=1, channels=1, width=2, rate=16000):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as target:
        target.setnchannels(channels); target.setsampwidth(width); target.setframerate(rate)
        sample=value.to_bytes(width,'little',signed=True)
        target.writeframes(sample*int(rate*seconds)*channels)
    return stream.getvalue()


class FakeFactory:
    def __init__(self, actions=None):
        self.actions=list(actions or []); self.calls=[]
    def __call__(self):
        owner=self
        class FakeTransport:
            network_calls=0
            def transcribe(self, data, *, display_name):
                owner.calls.append((data,display_name))
                self.network_calls+=4
                action=owner.actions.pop(0) if owner.actions else dict(
                    text='ЗОХИОМОЛ хоёр мянга хорин зургаан онд сургууль хаана вэ?',model=study.MODEL,
                    cleanup=dict(attempted=True,deleted=True,error=None))
                if isinstance(action,BaseException):
                    raise action
                return action
        return FakeTransport()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in study.BIND_CODE:
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# FAKE frozen source',encoding='utf-8')
        self.vocab=self.root/'config/stt-vocabulary.json'; self.vocab.parent.mkdir()
        self.vocab.write_text(json.dumps(dict(model=study.MODEL,enabled=True,terms=['ЗОХИОМОЛ'])),encoding='utf-8')
        self.bundle=self.root/'runtime/stt-new-speakers-20261105'; (self.bundle/'audio').mkdir(parents=True)
        self.manifest=self.bundle/'manifest.json'
        self.value=dict(schema_version=1,new_speakers_confirmed=True,clips=[])
        for i in range(2):
            path=self.bundle/'audio'/f'fake-{i}.wav'; path.write_bytes(fake_wav(100+i))
            self.value['clips'].append(dict(clip_id=f'FAKE-{i}',speaker_code=f'sp0{i+1}',consent=True,
                question_id='Q01',reference_text='ЗОХИОМОЛ хоёр мянга хорин зургаан онд сургууль хаана вэ?',
                audio_path=f'audio/fake-{i}.wav'))
        self.save()
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'))
        self.network.start(); self.addCleanup(self.network.stop)

    def save(self):
        self.manifest.write_text(json.dumps(self.value,ensure_ascii=False),encoding='utf-8')
    def captured(self):
        return study.capture(self.manifest,root=self.root)

    def test_dry_run_is_read_only_and_does_not_construct_credentials_or_transport(self):
        before={p:p.read_bytes() for p in (self.manifest,self.vocab,self.bundle/'audio/fake-0.wav')}
        with patch.object(study,'_real_factory',side_effect=AssertionError('NO CREDENTIALS')):
            captured=self.captured(); report=study.dry_report(captured)
        self.assertEqual(report['clips'],2)
        self.assertEqual(report['max_transcription_attempts'],4)
        self.assertEqual(report['max_http_requests'],16)
        self.assertEqual(report['network_calls'],0)
        self.assertFalse(captured['output'].exists())
        self.assertTrue(all(path.read_bytes()==data for path,data in before.items()))

    def test_bare_cli_is_dry_and_never_prints_reference_or_path(self):
        out=io.StringIO()
        with patch.object(study,'ROOT',self.root), patch.object(study,'_real_factory') as real, redirect_stdout(out):
            self.assertEqual(study.main(['--manifest',str(self.manifest)]),0)
        real.assert_not_called()
        self.assertTrue(json.loads(out.getvalue())['dry_run'])
        self.assertNotIn(self.value['clips'][0]['reference_text'],out.getvalue())
        self.assertNotIn('fake-0.wav',out.getvalue())

    def test_consent_requires_exact_true_before_audio_read(self):
        for consent in (False,1,'true',None):
            self.value['clips'][1]['consent']=consent; self.save()
            with self.subTest(consent=consent), patch.object(study,'_wav') as audio:
                with self.assertRaisesRegex(study.StudyError,'consent_required'):
                    self.captured()
                audio.assert_not_called()

    def test_reference_must_be_nonempty_meaningful_and_bounded(self):
        for reference in ('','   ','?!','😀','x'*1001):
            self.value['clips'][0]['reference_text']=reference; self.save()
            with self.subTest(length=len(reference)),self.assertRaises(study.StudyError): self.captured()

    def test_clip_and_speaker_case_aliases_are_rejected(self):
        self.value['clips'][1]['clip_id']='fake-0'; self.save()
        with self.assertRaisesRegex(study.StudyError,'duplicate_clip_id'): self.captured()
        self.value['clips'][1]['clip_id']='FAKE-1'; self.value['clips'][1]['speaker_code']='SP01'; self.save()
        with self.assertRaisesRegex(study.StudyError,'speaker_codes_differ_only_by_case'): self.captured()

    def test_audio_path_cannot_escape_new_bundle(self):
        outside=self.root/'runtime/old.wav'; outside.write_bytes(fake_wav())
        for path in ('../old.wav',str(outside)):
            self.value['clips'][0]['audio_path']=path; self.save()
            with self.subTest(absolute=Path(path).is_absolute()),self.assertRaises(study.StudyError): self.captured()

    def test_manifest_must_be_under_a_dated_new_speaker_bundle(self):
        wrong=self.root/'runtime/old-manifest.json'; wrong.write_bytes(self.manifest.read_bytes())
        with self.assertRaises(study.StudyError): study.capture(wrong,root=self.root)

    def test_duplicate_audio_cannot_inflate_speakers(self):
        (self.bundle/'audio/fake-1.wav').write_bytes((self.bundle/'audio/fake-0.wav').read_bytes())
        with self.assertRaisesRegex(study.StudyError,'duplicate_audio_in_study'): self.captured()

    def test_known_old_hash_is_rejected_without_opening_old_audio(self):
        old=self.root/study.LEGACY_MANIFEST; old.parent.mkdir(parents=True)
        old.write_text(json.dumps(dict(human_rows=[dict(audio_sha256=hashlib.sha256(
            (self.bundle/'audio/fake-0.wav').read_bytes()).hexdigest(),audio_path='NEVER-OPEN.wav')])),encoding='utf-8')
        with self.assertRaisesRegex(study.StudyError,'legacy_audio_cannot_be_a_new_speaker'): self.captured()
        self.assertFalse((old.parent/'NEVER-OPEN.wav').exists())

    def test_invalid_audio_formats_and_lengths_are_rejected(self):
        path=self.bundle/'audio/fake-0.wav'
        for data in (b'not a WAV',fake_wav(seconds=.1),fake_wav(seconds=31),
                     fake_wav(channels=2),fake_wav(width=1),fake_wav(rate=4000),fake_wav()[:-20]):
            path.write_bytes(data)
            with self.subTest(size=len(data)),self.assertRaises(study.StudyError): self.captured()

    def test_future_execute_requires_both_attestations(self):
        captured=self.captured()
        with patch.object(study,'_real_factory') as real:
            with self.assertRaisesRegex(study.StudyError,'free_tier_confirmation_required'): study.execute(captured)
            real.assert_not_called()
        self.value['new_speakers_confirmed']=False; self.save(); captured=self.captured()
        self.assertFalse(study.dry_report(captured)['ready_for_future_execute'])
        with self.assertRaisesRegex(study.StudyError,'new_speakers_operator_confirmation_required'):
            study.execute(captured,transport_factory=FakeFactory(),pause=0)

    def test_fake_run_two_arms_original_unchanged_and_no_references_sent(self):
        captured=self.captured(); factory=FakeFactory(); original=(self.bundle/'audio/fake-0.wav').read_bytes()
        report=study.execute(captured,transport_factory=factory,pause=0)
        self.assertTrue(report['completed']); self.assertEqual(report['paired_clips'],2)
        self.assertEqual(len(factory.calls),4); self.assertEqual(report['http_requests'],16)
        self.assertEqual(factory.calls[0][0],original); self.assertNotEqual(factory.calls[1][0],original)
        self.assertEqual((self.bundle/'audio/fake-0.wav').read_bytes(),original)
        for _,name in factory.calls:
            self.assertRegex(name,r'^clip-[0-9a-f]{16}-(?:raw|clean)$')
            self.assertNotIn(self.value['clips'][0]['reference_text'],name)
        self.assertNotIn(self.value['clips'][0]['reference_text'],json.dumps(report,ensure_ascii=False))
        self.assertIn(self.value['clips'][0]['reference_text'],(captured['output']/'attempts.jsonl').read_text(encoding='utf-8'))

    def test_counterbalancing_is_per_speaker(self):
        self.value['clips'][1]['speaker_code']='sp01'; self.save()
        schedule=self.captured()['plan']['schedule']
        self.assertEqual([s['arm'] for s in schedule],list(study.ARMS)+list(reversed(study.ARMS)))

    def test_first_429_stops_and_resume_does_not_retry_failed_arm(self):
        captured=self.captured(); first=FakeFactory([study.CandidateError('http_429')])
        report=study.execute(captured,transport_factory=first,pause=0)
        self.assertEqual(report['stopped'],'http_429'); self.assertEqual(len(first.calls),1)
        second=FakeFactory(); report=study.execute(self.captured(),transport_factory=second,resume=True,pause=0)
        self.assertEqual(len(second.calls),3); self.assertEqual(report['attempts_reserved'],4)
        self.assertFalse(report['completed']); self.assertEqual(report['paired_clips'],1)
        third=FakeFactory(); study.execute(self.captured(),transport_factory=third,resume=True,pause=0)
        self.assertEqual(third.calls,[])

    def test_cleanup_429_is_not_hidden_by_primary_error_and_partial_text(self):
        partial=dict(text='FAKE partial secret',model=study.MODEL,
                     cleanup=dict(attempted=True,deleted=False,error='http_429'))
        factory=FakeFactory([study.CandidateError('uploaded_file_cleanup_failed',partial)])
        report=study.execute(self.captured(),transport_factory=factory,pause=0)
        self.assertEqual(len(factory.calls),1); self.assertEqual(report['stopped'],'http_429')
        self.assertEqual(report['paired_clips'],0)
        self.assertNotIn('FAKE partial secret',json.dumps(report))

    def test_non429_failure_is_consumed_and_not_retried(self):
        factory=FakeFactory([RuntimeError('FAKE private key and transcript')])
        report=study.execute(self.captured(),transport_factory=factory,pause=0)
        self.assertEqual(len(factory.calls),4); self.assertEqual(report['paired_clips'],1)
        journal=(self.bundle/'measurement/attempts.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('FAKE private key and transcript',journal)
        resumed=FakeFactory(); study.execute(self.captured(),transport_factory=resumed,resume=True,pause=0)
        self.assertEqual(resumed.calls,[])

    def test_wrong_model_is_not_scored_as_success(self):
        factory=FakeFactory([dict(text='FAKE',model='wrong-model')])
        report=study.execute(self.captured(),transport_factory=factory,pause=0)
        self.assertEqual(report['paired_clips'],1)

    def test_reserved_unfinished_attempt_is_never_dispatched_again(self):
        captured=self.captured(); factory=FakeFactory(); append=study._append
        def interrupted(path,value):
            if value['event']=='finish': raise OSError('FAKE crash after provider')
            append(path,value)
        with patch.object(study,'_append',side_effect=interrupted),self.assertRaises(OSError):
            study.execute(captured,transport_factory=factory,pause=0)
        self.assertEqual(len(factory.calls),1)
        resumed=FakeFactory(); report=study.execute(self.captured(),transport_factory=resumed,resume=True,pause=0)
        self.assertEqual(len(resumed.calls),3); self.assertEqual(report['unfinished_attempts'],1)
        self.assertFalse(report['http_requests_complete'])
        self.assertEqual(report['http_requests_upper_bound'],16)

    def test_resume_rejects_manifest_audio_vocabulary_or_code_drift(self):
        study.execute(self.captured(),transport_factory=FakeFactory([study.CandidateError('http_429')]),pause=0)
        before=self.manifest.read_bytes(); self.value['clips'][0]['reference_text']+=' FAKE changed'; self.save()
        with self.assertRaisesRegex(study.StudyError,'resume_inputs_or_code_changed'):
            study.execute(self.captured(),transport_factory=FakeFactory(),resume=True,pause=0)
        self.manifest.write_bytes(before)
        self.vocab.write_text(json.dumps(dict(model=study.MODEL,terms=['FAKE changed'])),encoding='utf-8')
        with self.assertRaisesRegex(study.StudyError,'resume_inputs_or_code_changed'):
            study.execute(self.captured(),transport_factory=FakeFactory(),resume=True,pause=0)

    def test_revocation_during_pause_prevents_next_dispatch(self):
        captured=self.captured(); factory=FakeFactory()
        def revoke(_):
            self.value['clips'][0]['consent']=False; self.save()
        with self.assertRaisesRegex(study.StudyError,'consent_or_reference_changed_before_dispatch'):
            study.execute(captured,transport_factory=factory,pause=1,sleeper=revoke)
        self.assertEqual(len(factory.calls),1)

    def test_live_lock_prevents_concurrent_resume(self):
        output=self.bundle/'measurement'
        with study.run_lock(output):
            with self.assertRaisesRegex(study.StudyError,'study_is_already_running'):
                with study.run_lock(output): pass
        with study.run_lock(output): pass

    def test_torn_or_duplicate_journal_fails_closed(self):
        captured=self.captured(); path=self.bundle/'broken.jsonl'; path.write_bytes(b'{"event":"start"')
        with self.assertRaisesRegex(study.StudyError,'journal_corrupt_do_not_retry'): study.load_journal(path,captured['plan'])

    def test_symlink_output_is_rejected_before_private_write(self):
        outside=self.root/'FAKE-outside'; outside.mkdir()
        output=self.bundle/'measurement'
        try:
            output.symlink_to(outside,target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit creating a real directory symlink')
        with self.assertRaisesRegex(study.StudyError,'unsafe_private_output_path'): self.captured()
        self.assertEqual(list(outside.iterdir()),[])

    def test_hardlinked_journal_is_rejected_before_append(self):
        output=self.bundle/'measurement'; output.mkdir()
        outside=self.root/'FAKE-outside.jsonl'; outside.write_bytes(b'FAKE untouched')
        try:
            os.link(outside,output/'attempts.jsonl')
        except OSError:
            self.skipTest('OS does not permit creating a real hard link')
        with self.assertRaisesRegex(study.StudyError,'unsafe_private_artifact_path'): self.captured()
        self.assertEqual(outside.read_bytes(),b'FAKE untouched')

    def test_present_empty_legacy_registry_is_not_verified(self):
        old=self.root/study.LEGACY_MANIFEST; old.parent.mkdir(parents=True)
        old.write_text('{"human_rows":[]}',encoding='utf-8')
        with self.assertRaisesRegex(study.StudyError,'legacy_hash_metadata_invalid'): self.captured()

    def test_deleted_journal_cannot_reset_call_budget(self):
        captured=self.captured()
        study.execute(captured,transport_factory=FakeFactory([study.CandidateError('http_429')]),pause=0)
        (captured['output']/'attempts.jsonl').unlink()
        fake=FakeFactory()
        with self.assertRaisesRegex(study.StudyError,'journal_reservations_missing_do_not_retry'):
            study.execute(self.captured(),transport_factory=fake,resume=True,pause=0)
        self.assertEqual(fake.calls,[])

    def test_crash_after_journal_before_counter_still_consumes_attempt(self):
        captured=self.captured(); original=study._attempt_state
        def crash(output,plan,reserved):
            if reserved==1: raise OSError('FAKE crash before dispatch')
            original(output,plan,reserved)
        fake=FakeFactory()
        with patch.object(study,'_attempt_state',side_effect=crash),self.assertRaises(OSError):
            study.execute(captured,transport_factory=fake,pause=0)
        self.assertEqual(fake.calls,[])
        resumed=FakeFactory(); report=study.execute(self.captured(),transport_factory=resumed,resume=True,pause=0)
        self.assertEqual(len(resumed.calls),3)
        self.assertEqual(report['attempts_reserved'],4)
        self.assertEqual(report['unfinished_attempts'],1)

    def test_cli_errors_never_echo_private_exception(self):
        output=io.StringIO()
        with patch.object(study,'capture',side_effect=RuntimeError('FAKE SECRET REFERENCE KEY')),redirect_stdout(output):
            self.assertEqual(study.main(['--manifest','FAKE']),1)
        self.assertNotIn('FAKE SECRET',output.getvalue())

    def test_invalid_cli_arguments_cannot_echo_accidentally_pasted_key(self):
        output=io.StringIO()
        with redirect_stdout(output):
            result=study.main(['--manifest','FAKE','--api-key','FAKE-SECRET-KEY'])
        self.assertEqual(result,1)
        self.assertNotIn('FAKE-SECRET-KEY',output.getvalue())

    def test_cleanup_429_also_stops_when_original_failure_was_timeout(self):
        partial=dict(text='FAKE partial',model=study.MODEL,
                     cleanup=dict(attempted=True,deleted=False,error='http_429'))
        fake=FakeFactory([study.CandidateError('timeout',partial)])
        result=study.execute(self.captured(),transport_factory=fake,pause=0)
        self.assertEqual(result['stopped'],'http_429')
        self.assertEqual(len(fake.calls),1)

    def test_mutated_capture_cannot_write_raw_into_public_directory(self):
        captured=self.captured(); captured['output']=self.root/'data'
        fake=FakeFactory()
        with self.assertRaisesRegex(study.StudyError,'private_study_output_required'):
            study.execute(captured,transport_factory=fake,pause=0)
        self.assertEqual(fake.calls,[])
        self.assertFalse((self.root/'data').exists())

    def test_stale_capture_rejects_changed_code_before_any_dispatch(self):
        captured=self.captured()
        (self.root/study.BIND_CODE[0]).write_text('# FAKE changed code',encoding='utf-8')
        fake=FakeFactory()
        with self.assertRaisesRegex(study.StudyError,'captured_inputs_or_code_changed'):
            study.execute(captured,transport_factory=fake,pause=0)
        self.assertEqual(fake.calls,[])

    def test_real_factory_would_use_same_v2_terms_without_loading_saved_key(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':'FAKE-KEY-NOT-REAL'}), patch.object(study,'GeminiTransport') as transport:
            factory=study._real_factory(['ЗОХИОМОЛ'])
            factory(); factory()
        self.assertEqual(transport.call_count,2)
        self.assertTrue(all(call.kwargs=={'vocabulary':['ЗОХИОМОЛ']} for call in transport.call_args_list))


class RecordingKitTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.kit=self.root/'data/stt-recording-kit'

    def test_fifteen_questions_use_existing_different_topics(self):
        text=(self.kit/'questions.mn.md').read_text(encoding='utf-8')
        rows=re.findall(r'^\|\s*(Q\d+)\s*\|\s*`([^`]+)`\s*\|',text,re.M)
        self.assertEqual([r[0] for r in rows],[f'Q{i:02}' for i in range(1,16)])
        self.assertEqual(len({r[1] for r in rows}),15)
        declared=json.loads((self.root/'config/knowledge-topics.json').read_text(encoding='utf-8'))
        serialized=json.dumps(declared,ensure_ascii=False)
        for _,topic in rows:
            self.assertIn('"'+topic+'"',serialized)

    def test_example_is_not_consent_or_an_actual_recording(self):
        example=json.loads((self.kit/'manifest.example.json').read_text(encoding='utf-8'))
        self.assertFalse(example['new_speakers_confirmed'])
        self.assertFalse(example['clips'][0]['consent'])
        self.assertEqual(example['clips'][0]['reference_text'],'')
        self.assertFalse(list(self.kit.rglob('*.wav')))

    def test_instructions_separate_cloud_execute_and_evaluation_only_consent(self):
        readme=(self.kit/'README.mn.md').read_text(encoding='utf-8')
        consent=(self.kit/'consent.mn.md').read_text(encoding='utf-8')
        self.assertIn('--dry-run',readme)
        self.assertIn('--execute',readme)
        self.assertIn('--free-tier-confirmed',readme)
        self.assertIn('evaluation_only',consent)
        self.assertIn('шинээр баталгаажуулаагүй',consent)


if __name__=='__main__': unittest.main()
