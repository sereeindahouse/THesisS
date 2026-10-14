import unittest
from tools.voice_report import render


class PrivateVoiceReportTests(unittest.TestCase):
    def test_transcript_and_answer_markup_are_escaped_and_audio_is_local(self):
        report=dict(synthetic_voice=True,created_utc='2026-10-14',completed_clips=1,cases=[dict(
            id='safe01',voice='mn-MN-BataaNeural',query='<script>alert(1)</script>',
            raw_stt='<img onerror=x>',raw_response=dict(route='E',message='<iframe src=x>'))])
        html=render(report)
        self.assertNotIn('<script>',html);self.assertNotIn('<img ',html);self.assertNotIn('<iframe ',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('src="safe01-bataa-question.mp3"',html)
        self.assertIn('1 / 1',html)

    def test_path_traversal_case_id_is_rejected(self):
        report=dict(synthetic_voice=True,cases=[dict(id='../outside',voice='Bataa',query='q')])
        with self.assertRaises(ValueError):render(report)

    def test_human_audio_report_cannot_be_labelled_synthetic_by_renderer(self):
        with self.assertRaises(ValueError):render(dict(synthetic_voice=False,cases=[]))


if __name__=='__main__':unittest.main()
