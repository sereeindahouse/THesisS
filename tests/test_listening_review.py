"""Invented temporary fixtures only; never confirm the real pilot or rate its TTS."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import listening_review
from listening_review import ListeningReview, PENDING_IDS, TTS_IDS, TTS_DIRECTORY


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ListeningReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        (self.root / 'audio').mkdir()
        (self.root / TTS_DIRECTORY).mkdir(parents=True)
        rows, entries = [], []
        for n in range(1, 21):
            identifier = f'q{n:02}'
            pending = identifier in PENDING_IDS
            audio = b'Invented WAV fixture ' + identifier.encode()
            (self.root / 'audio' / (identifier + '.wav')).write_bytes(audio)
            rows.append(dict(id=identifier, prompt='Invented question ' + identifier,
                audio_path='audio/' + identifier + '.wav', speaker_id='fixture-speaker',
                reference='' if pending or identifier == 'q05' else 'Invented previously confirmed ' + identifier,
                evaluation_status='excluded_by_user' if identifier == 'q05' else 'needs_reference_confirmation' if pending else 'eligible_speaker_confirmed',
                notes='Existing notes; invented test only.'))
            if pending:
                entry = dict(id=identifier, audio_path='audio/' + identifier + '.wav',
                    audio_sha256=hashlib.sha256(audio).hexdigest(), displayed_question='Invented question ' + identifier,
                    draft_model_text='Unconfirmed draft ' + identifier, confirmed_reference='',
                    status='needs_speaker_listening_review')
                if identifier == 'q16':
                    entry['previous_partial_reference'] = 'дугаар руу залгана уу'
                entries.append(entry)
        write_csv(self.root / 'data/stt-pilot.csv', rows)
        (self.root / 'data/stt-reference-review-20261009.json').write_text(json.dumps(dict(entries=entries)), encoding='utf-8')
        (self.root / 'data/stt-model-choice.json').write_text(json.dumps(dict(development_run='results/invented-run', remaining_reference_reviews=list(PENDING_IDS),
            selection_metrics={'corpus_wer': .36}, current_reference_evaluation={'reference_inventory_sha256':'old'})), encoding='utf-8')
        self.tts_rows = [dict(file='results/old.mp3', listener='old-listener', overall='bad_user_report', intelligibility='',
                            pronunciation_errors='', names_acronyms='', numbers_dates='', noise_or_breaks='', review_details='Keep old evidence.')]
        tests = []
        for identifier in TTS_IDS:
            path = TTS_DIRECTORY + '/' + identifier + '.mp3'
            (self.root / path).write_bytes(b'Invented MP3 ' + identifier.encode())
            self.tts_rows.append(dict(file=path.replace('/', '\\'), listener='', overall='listening_pending', intelligibility='',
                pronunciation_errors='', names_acronyms='', numbers_dates='', noise_or_breaks='', review_details='Controlled fixture.'))
            tests.append(dict(id=identifier, voice='mn-MN-fixture', text='Invented pronunciation fixture', file=path.replace('/', '\\'), listening_status='pending'))
        write_csv(self.root / 'data/tts-listening-review.csv', self.tts_rows)
        (self.root / TTS_DIRECTORY / 'manifest.json').write_text(json.dumps(dict(tests=tests)), encoding='utf-8')
        self.review = ListeningReview(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, name='stt-pilot.csv'):
        with (self.root / 'data' / name).open(encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))

    def before(self):
        return {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_status_is_read_only_and_lists_exact_pending_and_three_tts(self):
        before = self.before()
        status = self.review.status()
        self.assertTrue(status['available'])
        self.assertEqual([e['id'] for e in status['pending_stt']], list(PENDING_IDS))
        self.assertEqual(status['eligible_stt_count'], 13)
        self.assertEqual(status['excluded_stt_ids'], ['q05'])
        self.assertEqual(status['pending_tts_count'], 3)
        self.assertEqual(status['reviewed_tts_count'], 0)
        self.assertFalse(status['automatic_confirmation'])
        self.assertIn('дугаар', next(e for e in status['pending_stt'] if e['id']=='q16')['note'])
        self.assertEqual(before, self.before())

    def test_public_clone_missing_private_data_is_graceful(self):
        empty = self.root / 'empty-public-clone'
        empty.mkdir()
        status = ListeningReview(empty).status()
        self.assertFalse(status['available'])
        self.assertEqual(status['pending_stt'], [])
        self.assertEqual(status['tts'], [])

    def test_only_whitelisted_audio_is_exposed(self):
        self.assertEqual(self.review.audio('stt', 'q10')[1], 'audio/wav')
        self.assertEqual(self.review.audio('tts', 'bataa-raw')[1], 'audio/mpeg')
        for kind, identifier in [('stt', 'q05'), ('stt', 'q01'), ('stt', '../q10'), ('tts', '../../secrets'), ('other', 'q10')]:
            with self.subTest(kind=kind, identifier=identifier), self.assertRaises(ValueError):
                self.review.audio(kind, identifier)

    def test_stt_requires_explicit_boolean_and_literal_full_text(self):
        before = self.before()
        for confirmation in [False, None, 1, 'true']:
            with self.subTest(confirmed=confirmation), self.assertRaises(ValueError):
                self.review.confirm_stt('q10', 'Invented full spoken text', confirmation)
        for text in ['', '  ', 'q', 'quit', 'skip', 'зөв', 'yes', None, 'a'*6001]:
            with self.subTest(text=str(text)[:20]), self.assertRaises(ValueError):
                self.review.confirm_stt('q10', text, True)
        self.assertEqual(before, self.before())

    def test_q05_and_other_confirmed_references_cannot_be_reintroduced(self):
        before = self.before()
        for identifier in ['q05', 'q01', 'q04', 'q18', '../q10']:
            with self.subTest(id=identifier), self.assertRaises(ValueError):
                self.review.confirm_stt(identifier, 'Invented full text', True)
        self.assertEqual(before, self.before())

    def test_q16_rejects_known_incomplete_reference_without_guessing_number(self):
        before = self.before()
        with self.assertRaises(ValueError):
            self.review.confirm_stt('q16', ' ДУГААР руу залгана уу. ', True)
        self.assertEqual(before, self.before())
        result = self.review.confirm_stt('q16', 'Тестийн нэг хоёр гурав дугаар руу залгана уу', True)
        self.assertTrue(result['saved'])
        row = next(r for r in self.rows() if r['id']=='q16')
        self.assertEqual(row['reference'], 'Тестийн нэг хоёр гурав дугаар руу залгана уу')

    def test_stt_audio_hash_change_blocks_save_and_status(self):
        (self.root / 'audio/q10.wav').write_bytes(b'changed fixture')
        before = self.before()
        with self.assertRaises(ValueError):
            self.review.confirm_stt('q10', 'Invented full text', True)
        with self.assertRaises(ValueError):
            self.review.status()
        self.assertEqual(before, self.before())

    def test_metadata_path_escape_blocks_audio_and_human_save(self):
        path = self.root / 'data/stt-reference-review-20261009.json'
        data = json.loads(path.read_text())
        data['entries'][0]['audio_path']='../secret.wav'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.review.audio('stt', 'q10')
        with self.assertRaises(ValueError):
            self.review.confirm_stt('q10', 'Invented full text', True)

    def test_confirmation_preserves_thirteen_old_refs_exclusion_and_original_audio(self):
        before_rows = {r['id']: r for r in self.rows()}
        audio_before = {p:p.read_bytes() for p in (self.root/'audio').glob('*.wav')}
        result = self.review.confirm_stt('q10', '  Invented exact spoken answer 2026.  ', True)
        self.assertTrue(result['saved'])
        self.assertEqual(result['pending_stt_count'], 5)
        self.assertFalse(result['inference_repeated'])
        current = {r['id']:r for r in self.rows()}
        for identifier in before_rows:
            if identifier!='q10':
                self.assertEqual(current[identifier], before_rows[identifier])
        self.assertEqual(current['q10']['reference'], 'Invented exact spoken answer 2026.')
        self.assertEqual(current['q10']['evaluation_status'], 'eligible_speaker_confirmed')
        choice = json.loads((self.root/'data/stt-model-choice.json').read_text())
        self.assertEqual(choice['remaining_reference_reviews'], list(PENDING_IDS)[1:])
        self.assertEqual(choice['selection_metrics'], {'corpus_wer':.36})
        self.assertTrue(choice['current_reference_evaluation']['stale_after_reference_review'])
        review=json.loads((self.root/'data/stt-reference-review-20261009.json').read_text())
        self.assertEqual(review['entries'][0]['confirmation_source'], 'speaker_explicit_web_confirmation')
        self.assertEqual(audio_before, {p:p.read_bytes() for p in (self.root/'audio').glob('*.wav')})
        journal=json.loads(next((self.root/'data/listening-review-history').glob('*/journal.json')).read_text())
        self.assertEqual(journal['state'], 'committed')
        self.assertEqual(len(journal['files']), 3)
        self.assertTrue(journal['human_confirmed'])
        self.assertFalse(journal['model_draft_auto_confirmed'])
        self.assertEqual(self.review.status()['eligible_stt_count'], 14)

    def test_double_confirmation_rejected_and_parallel_other_id_preserved(self):
        def submit(identifier):
            return ListeningReview(self.root).confirm_stt(identifier, 'Invented human text '+identifier, True)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(submit, ['q10','q13']))
        self.assertTrue(all(r['saved'] for r in results))
        self.assertEqual(self.review.status()['eligible_stt_count'], 15)
        before=self.before()
        with self.assertRaises(ValueError):
            self.review.confirm_stt('q10', 'Different invented text', True)
        self.assertEqual(before, self.before())

    def test_unique_backup_and_journal_for_each_actual_fixture_action(self):
        self.review.confirm_stt('q10', 'Fixture answer one', True)
        self.review.confirm_stt('q13', 'Fixture answer two', True)
        histories=list((self.root/'data/listening-review-history').iterdir())
        self.assertEqual(len(histories), 2)
        self.assertNotEqual(histories[0].name, histories[1].name)
        self.assertTrue(all(len(list(p.glob('*.before')))==3 for p in histories))

    def test_multifile_write_failure_rolls_back_reference_and_keeps_backups(self):
        inventory=self.root/'data/stt-pilot.csv'
        review=self.root/'data/stt-reference-review-20261009.json'
        before_inventory=inventory.read_bytes()
        before_review=review.read_bytes()
        original=listening_review._atomic_replace
        def fail_review(path,data):
            if path==review:
                raise OSError('invented write failure')
            return original(path,data)
        with patch.object(listening_review,'_atomic_replace',side_effect=fail_review):
            with self.assertRaises(RuntimeError):
                self.review.confirm_stt('q10', 'Fixture human answer', True)
        self.assertEqual(inventory.read_bytes(),before_inventory)
        self.assertEqual(review.read_bytes(),before_review)
        journal=json.loads(next((self.root/'data/listening-review-history').glob('*/journal.json')).read_text())
        self.assertEqual(journal['state'],'rolled_back')

    def test_tts_listener_boolean_and_both_scores_required(self):
        before=self.before()
        invalid=[('',4,4,True),('fixture',0,4,True),('fixture',6,4,True),('fixture',True,4,True),('fixture',4,'4',True),('fixture',4,4,False),('fixture',4,4,1)]
        for listener,overall,intelligibility,confirmation in invalid:
            with self.subTest(values=(listener,overall,intelligibility,confirmation)), self.assertRaises(ValueError):
                self.review.save_tts('bataa-raw',listener,overall,intelligibility,'',confirmation)
        self.assertEqual(before,self.before())

    def test_tts_saves_only_one_row_keeps_manifest_and_old_ratings_without_mos(self):
        before=self.rows('tts-listening-review.csv')
        manifest=self.root/TTS_DIRECTORY/'manifest.json'
        manifest_before=manifest.read_bytes()
        self.review.status()
        result=self.review.save_tts('bataa-spoken','fixture listener',4,5,'Invented acronym error',True)
        after=self.rows('tts-listening-review.csv')
        self.assertEqual(before[0],after[0])
        self.assertEqual(before[1],after[1])
        self.assertEqual(before[3],after[3])
        self.assertEqual(after[2]['overall'],'4')
        self.assertEqual(after[2]['intelligibility'],'5')
        self.assertEqual(after[2]['listener'],'fixture listener')
        self.assertFalse(result['mos_computed'])
        self.assertFalse(result['final_voice_selected'])
        self.assertFalse(result['production_accepted'])
        self.assertEqual(manifest_before,manifest.read_bytes())
        self.assertEqual(self.review.status()['reviewed_tts_count'],1)
        self.assertEqual(self.review.status()['pending_tts_count'],2)

    def test_tts_file_replacement_after_display_is_rejected(self):
        self.review.status()
        (self.root/TTS_DIRECTORY/'bataa-raw.mp3').write_bytes(b'changed fixture')
        before=self.before()
        with self.assertRaises(ValueError):
            self.review.save_tts('bataa-raw','fixture',4,4,'',True)
        self.assertEqual(before,self.before())

    def test_tts_manifest_cannot_allow_arbitrary_private_file(self):
        path=self.root/TTS_DIRECTORY/'manifest.json'
        data=json.loads(path.read_text())
        data['tests'][0]['file']='data/secret.mp3'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.review.audio('tts','bataa-raw')

    def test_optional_rescoring_missing_helpers_does_not_run_inference_or_change_files(self):
        before=self.before()
        with patch.object(listening_review.subprocess,'run') as run:
            result=self.review.rescore_existing()
        run.assert_not_called()
        self.assertEqual(result['status'],'not_available')
        self.assertFalse(result['inference_repeated'])
        self.assertEqual(before,self.before())

    def test_stale_metrics_not_reported_as_current_after_reference_edit(self):
        directory=self.root/'results/current-human-reference-comparisons'
        directory.mkdir()
        (directory/'latest.json').write_text(json.dumps(dict(reference_inventory_sha256='old-inventory',
            runs=[dict(run='invented-run',scored_ids=['q01'],metrics={'corpus_wer':0})])),encoding='utf-8')
        self.assertIsNone(self.review.status()['current_reference_metrics'])


if __name__=='__main__':
    unittest.main()
