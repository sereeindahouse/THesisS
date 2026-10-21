"""Saved STT-to-query lineage without model calls or invented human references."""
import json
from pathlib import Path
import tempfile
import unittest

from voice_runtime import VoiceRuntime, VoiceRuntimeError, MAX_TEXT_CHARACTERS


class TranscriptionLineageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.voice = VoiceRuntime(self.root)
        self.raw = 'Сора тэтгэлэг 2026 оны мэдээлэл.'
        self.stt = self.voice._save(b'constructed test audio', 'audio/wav',
                                    dict(kind='stt', text=self.raw, reference_confirmed=False))

    def assert_voice_error(self, code, status, callback):
        with self.assertRaises(VoiceRuntimeError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, status)

    def test_raw_query_uses_the_saved_original_without_claiming_verification(self):
        result = self.voice.transcription_lineage(self.stt['id'], self.raw)
        self.assertEqual(result, dict(kind='raw_stt', transcription_id=self.stt['id'],
                                      raw_text=self.raw, submitted_text=self.raw, edited=False,
                                      manual_verification_claimed=False))

    def test_edited_query_preserves_original_year_name_and_words_as_separate_fields(self):
        query = 'Сакура тэтгэлэг 2027 оны мэдээлэл.'
        result = self.voice.transcription_lineage(self.stt['id'], query)
        self.assertEqual(result['kind'], 'edited_stt')
        self.assertTrue(result['edited'])
        self.assertEqual(result['raw_text'], self.raw)
        self.assertEqual(result['submitted_text'], query)
        self.assertFalse(result['manual_verification_claimed'])
        self.assertEqual(self.voice.transcription_lineage(self.stt['id'], self.raw)['raw_text'], self.raw)

    def test_lineage_uses_original_memory_snapshot_after_artifact_text_is_edited(self):
        _, info_path, _ = self.voice._records[self.stt['id']]
        altered = json.loads(info_path.read_text(encoding='utf-8'))
        altered['text'] = 'Changed on disk after transcription'
        info_path.write_text(json.dumps(altered), encoding='utf-8')
        self.assertEqual(self.voice.transcription_lineage(self.stt['id'], self.raw)['raw_text'], self.raw)

    def test_tts_record_cannot_claim_to_be_an_original_transcription(self):
        tts = self.voice._save(b'constructed mp3', 'audio/mpeg', dict(kind='tts', text='Not STT'))
        self.assert_voice_error('stt_lineage_kind', 409,
            lambda: self.voice.transcription_lineage(tts['id'], 'Not STT'))

    def test_unknown_and_other_runtime_ids_cannot_expose_stored_transcripts(self):
        other = VoiceRuntime(self.root)
        self.assert_voice_error('stt_lineage_missing', 404,
            lambda: other.transcription_lineage(self.stt['id'], self.raw))
        self.assert_voice_error('stt_lineage_missing', 404,
            lambda: self.voice.transcription_lineage('0' * 32, self.raw))

    def test_reset_removes_new_binding_capability_without_mutating_prior_snapshot(self):
        result = self.voice.transcription_lineage(self.stt['id'], self.raw)
        self.voice.reset([self.stt['id']])
        self.assertNotIn(self.stt['id'], self.voice._transcription_texts)
        self.assertEqual(result['raw_text'], self.raw)
        self.assert_voice_error('stt_lineage_missing', 404,
            lambda: self.voice.transcription_lineage(self.stt['id'], self.raw))

    def test_deleted_audio_or_metadata_does_not_establish_new_lineage(self):
        for index in (0, 1):
            with self.subTest(index=index):
                saved = self.voice._save(b'test', 'audio/wav', dict(kind='stt', text=self.raw))
                self.voice._records[saved['id']][index].unlink()
                self.assert_voice_error('stt_lineage_missing', 404,
                    lambda: self.voice.transcription_lineage(saved['id'], self.raw))

    def test_caller_cannot_modify_future_lineage_through_returned_dictionary(self):
        result = self.voice.transcription_lineage(self.stt['id'], self.raw)
        result['raw_text'] = 'Injected'
        result['manual_verification_claimed'] = True
        fresh = self.voice.transcription_lineage(self.stt['id'], self.raw)
        self.assertEqual(fresh['raw_text'], self.raw)
        self.assertFalse(fresh['manual_verification_claimed'])

    def test_empty_original_can_only_be_reported_as_edited_if_query_is_supplied(self):
        saved = self.voice._save(b'test', 'audio/wav', dict(kind='stt', text=''))
        result = self.voice.transcription_lineage(saved['id'], 'Гараар бичсэн асуулт')
        self.assertEqual(result['raw_text'], '')
        self.assertTrue(result['edited'])
        self.assertFalse(result['manual_verification_claimed'])

    def test_invalid_identifiers_and_invalid_queries_are_rejected(self):
        for identifier in (None, '../escape', '', 'a' * 31, 'A' * 32):
            with self.subTest(identifier=identifier):
                self.assert_voice_error('voice_id', 400,
                    lambda: self.voice.transcription_lineage(identifier, self.raw))
        for query in (None, '', '   ', ['query'], 'x' * (MAX_TEXT_CHARACTERS + 1)):
            with self.subTest(query_type=type(query).__name__):
                self.assert_voice_error('stt_lineage_query', 400,
                    lambda: self.voice.transcription_lineage(self.stt['id'], query))


if __name__ == '__main__':
    unittest.main()
