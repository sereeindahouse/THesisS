"""Source-bound partial answers must speak their missing-field notice."""
import unittest
from answer_contract import spoken_text


class PartialAnswerSpeechTests(unittest.TestCase):
    def test_partial_source_notice_spoken_and_renderer_markers_omitted(self):
        result=dict(answer_kind='partial_official_website_extract',
                    answer='Компани нь 2031 оны 6-р сараас хамтран ажилласан. [1]',
                    citations=[{'url':'https://example.org/constructed'}],
                    message='Эхэд платформын нэр заагаагүй.')
        self.assertEqual(spoken_text(result),'Эхэд платформын нэр заагаагүй. Компани нь 2031 оны 6-р сараас хамтран ажилласан.')
        self.assertTrue(result['answer'].endswith('[1]'))

    def test_direct_source_speaks_same_body_without_added_citation_number(self):
        result=dict(answer_kind='official_website_extract',answer='Суралцах түвшин N3 байна. [1]',citations=[{}])
        self.assertEqual(spoken_text(result),'Суралцах түвшин N3 байна.')

    def test_ordinary_bracketed_data_and_unbound_indices_remain(self):
        result=dict(answer_kind='official_website_extract',answer='Массив [1] доторх утга 2031. [9]',citations=[{}])
        self.assertEqual(spoken_text(result),result['answer'])

    def test_stored_faq_is_not_treated_as_a_rendered_source_quote(self):
        result=dict(answer_kind='official_website_stored_answer',answer='Эхийн жагсаалт [1]',citations=[{}])
        self.assertEqual(spoken_text(result),result['answer'])
