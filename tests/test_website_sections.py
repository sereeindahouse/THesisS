"""Page sections as answers to describing questions (website_sections.py, tools/build_website_sections.py).

INVENTED pages only: no saved school page, no server, no network, no model.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from answer_presentation import drop_yes, named_first, present  # noqa: E402
import build_website_sections as cutter  # noqa: E402
from reception_tables import ReceptionAnswerPath  # noqa: E402
from website_sections import (MAX_ANSWER_CHARS, Section, SectionIndex, asks_what, content_stems, describes, holds,  # noqa: E402
                              same_word, section_text, stem)

SITE = 'https://school.example'
PARAGRAPH = 'Энд оюутнууд бие даан суралцаж, багаар ажиллаж, чөлөөт цагаа өнгөрөөдөг тохилог орчин бүрдсэн.'


def section(path, title, heading, text=PARAGRAPH, **more):
    return Section(url=SITE + path, version=1, title=title, heading=heading, text=text, retrieved_at='2026-11-25', **more)


def index():
    return SectionIndex([
        section('/orchin', 'Суралцах орчин', 'Суралцах орчин', 'Сургалтын орчны ерөнхий танилцуулга энд байна. ' + PARAGRAPH),
        section('/orchin', 'Суралцах орчин', 'Уншлагын танхим', label='I. СУРГАЛТЫН ОРЧИН'),
        section('/orchin', 'Суралцах орчин', 'Нийтийн хоолны газар', 'Хоолны цэсийг сар бүр баталдаг. ' + PARAGRAPH,
                parent='Спорт, хоол, хөгжил'),
        section('/orchin', 'Суралцах орчин', 'Спорт, хоол, хөгжил', (PARAGRAPH + '\n') * 20),
        section('/tenhim/robot', 'Роботын тэнхим', 'Лаборатори, сургалтын орчин',
                'Тэнхим гурван лабораторитой. ' + PARAGRAPH),
        section('/tenhim/robot', 'Роботын тэнхим', 'Эрхэм зорилго'),
        section('/tenhim/himi', 'Химийн тэнхим', 'Эрхэм зорилго'),
        section('/tenhim/robot', 'Роботын тэнхим', 'Od Internet Co., Ltd.',
                'Od Internet компани нь үүлэн тооцооллын үйлчилгээ үзүүлдэг. ' + PARAGRAPH, parent='Хамтын ажиллагаа'),
        section('/news/ajil', 'ХҮҮХЭД ХАМГААЛЛЫН АЖИЛ', 'ХҮҮХЭД ХАМГААЛЛЫН АЖИЛ'),
        section('/news/naadam', 'НАМРЫН НААДАМ', 'НАМРЫН НААДАМ', 'Намрын наадам амжилттай боллоо. ' + PARAGRAPH),
        section('/news/zaal', 'Уншлагын танхим шинэчлэгдлээ', 'Уншлагын танхим шинэчлэгдлээ'),
    ], 'corpus1')


class WordKeyTests(unittest.TestCase):
    def test_forms_of_a_word_meet_also_when_a_vowel_falls_out(self):
        for one, other in (('газар', 'газрын'), ('тэнхим', 'тэнхмийн'), ('оюутан', 'оюутны'), ('орчин', 'орчны'),
                           ('дадлага', 'дадлагын'), ('лаборатори', 'лабораторийн'), ('хөтөлбөр', 'хөтөлбөрийн')):
            with self.subTest(one=one, other=other):
                self.assertTrue(same_word(stem(one), stem(other)))

    def test_different_words_do_not_meet(self):
        # The last two share a stem key; the words as written tell them apart (code review, 11/25).
        for one, other in (('үйл', 'үйлдвэр'), ('компьютер', 'компани'), ('танилцах', 'танхим'), ('ном', 'номер'),
                           ('чанар', 'чадвар'), ('зөвлөгөө', 'зөвлөл'), ('бэлтгэх', 'бэлтгэл')):
            with self.subTest(one=one, other=other):
                self.assertFalse(same_word(stem(one), stem(other)))

    def test_question_words_and_the_schools_name_are_not_content(self):
        self.assertEqual(content_stems('Танай сургуулийн уншлагын танхим гэж юу вэ?'), [stem('уншлагын'), stem('танхим')])


class QuestionFormTests(unittest.TestCase):
    def test_what_is_about_what_kind_is_there_and_a_bare_name_describe(self):
        for query in ('Уншлагын танхим гэж юу вэ?', 'Уншлагын танхимын талаар хэлж өгөөч', 'Уншлагын танхим ямар вэ?',
                      'Уншлагын танхим байдаг уу?', 'Уншлагын танхим'):
            with self.subTest(query=query):
                self.assertTrue(describes(query))

    def test_a_value_or_a_permission_question_does_not(self):
        for query in ('Уншлагын танхим хаана байдаг вэ?', 'Уншлагын танхим хэдэн цагт онгойдог вэ?',
                      'Уншлагын танхимд хоол идэж болох уу?', 'Уншлагын танхим ажилладаг уу?',
                      'Уншлагын танхимын утас', '2026 оны уншлагын танхим'):
            with self.subTest(query=query):
                self.assertFalse(describes(query))

    def test_only_what_is_about_and_a_bare_name_go_before_a_mapped_stored_answer(self):
        self.assertTrue(asks_what('Уншлагын танхим гэж юу вэ?'))
        self.assertTrue(asks_what('Уншлагын танхимын тухай'))
        self.assertTrue(asks_what('Уншлагын танхим'))
        self.assertFalse(asks_what('Уншлагын танхим байдаг уу?'))
        self.assertFalse(asks_what('Уншлагын танхим ямар вэ?'))


class FindTests(unittest.TestCase):
    def found(self, query):
        hit = index().find(query)
        return None if hit is None else (hit['section'].url.replace(SITE, ''), hit['section'].heading)

    def test_a_question_that_names_a_heading_gets_that_section(self):
        self.assertEqual(self.found('Нийтийн хоолны газрын талаар'), ('/orchin', 'Нийтийн хоолны газар'))
        self.assertEqual(self.found('Хоолны газар байдаг уу?'), ('/orchin', 'Нийтийн хоолны газар'))
        self.assertEqual(self.found('Роботын тэнхимийн лаборатори, сургалтын орчин ямар вэ?'),
                         ('/tenhim/robot', 'Лаборатори, сургалтын орчин'))

    def test_the_page_of_the_site_goes_before_a_news_item_with_the_same_words(self):
        self.assertEqual(self.found('Уншлагын танхим гэж юу вэ?'), ('/orchin', 'Уншлагын танхим'))

    def test_the_section_whose_own_name_is_said_most_fully_is_meant(self):
        # The label «I. СУРГАЛТЫН ОРЧИН» is said whole; «Лаборатори, сургалтын орчин» of another page only in part.
        self.assertEqual(self.found('Сургалтын орчин ямар вэ?'), ('/orchin', 'Уншлагын танхим'))

    def test_the_same_heading_on_two_pages_needs_the_page_named(self):
        self.assertIsNone(self.found('Эрхэм зорилго гэж юу вэ?'))
        self.assertEqual(self.found('Химийн тэнхимийн эрхэм зорилго юу вэ?'), ('/tenhim/himi', 'Эрхэм зорилго'))

    def test_a_word_outside_the_names_is_allowed_once_in_a_long_question_and_must_be_in_the_text(self):
        self.assertEqual(self.found('Od Internet компанитай хамтын ажиллагааны талаар'),
                         ('/tenhim/robot', 'Od Internet Co., Ltd.'))
        self.assertIsNone(self.found('Od Internet банктай хамтын ажиллагааны талаар'))     # «банк» is nowhere in it
        self.assertIsNone(self.found('Уншлагын танхимын цэс'))                               # three words, one outside

    def test_one_word_must_be_the_whole_name(self):
        self.assertIsNone(self.found('Хамгаалалт байдаг уу?'))         # not «Хүүхэд хамгааллын ажил»
        self.assertIsNone(self.found('Лаборатори гэж юу вэ?'))

    def test_a_label_must_be_said_whole(self):
        self.assertIsNone(self.found('Сургалтын тухай'))                 # half of the label «I. СУРГАЛТЫН ОРЧИН»

    def test_a_question_that_names_only_the_page_gets_no_section_of_it(self):
        self.assertIsNone(self.found('Роботын тэнхимийн талаар'))

    def test_a_question_about_a_property_of_the_thing_gets_nothing(self):
        for query in ('Нийтийн хоолны газар ямар цагаар ажилладаг вэ?', 'Нийтийн хоолны газар хаана байдаг вэ?',
                      'Нийтийн хоолны газарт карт уншуулж болох уу?', 'Дотуур байр байдаг уу?'):
            with self.subTest(query=query):
                self.assertIsNone(self.found(query))

    def test_a_news_item_is_found_by_its_title(self):
        hit = index().find('Намрын наадмын талаар')
        self.assertEqual(hit['section'].heading, 'НАМРЫН НААДАМ')
        self.assertTrue(hit['news'])

    def test_an_empty_index_and_a_file_of_another_corpus_find_nothing(self):
        self.assertIsNone(SectionIndex().find('Уншлагын танхим гэж юу вэ?'))
        self.assertFalse(SectionIndex.from_file(Path(__file__).parent / 'no-such-folder', 'corpus1'))


class ShownTextTests(unittest.TestCase):
    def test_the_name_and_page_stand_above_the_text(self):
        shown = section_text(section('/orchin', 'Суралцах орчин', 'Уншлагын танхим'))
        self.assertEqual(shown, 'Уншлагын танхим (Суралцах орчин)\n' + PARAGRAPH)
        self.assertEqual(section_text(section('/orchin', 'Суралцах орчин', 'Суралцах орчин')), 'Суралцах орчин\n' + PARAGRAPH)

    def test_a_long_text_is_cut_at_a_lines_end(self):
        shown = section_text(section('/orchin', 'Суралцах орчин', 'Спорт', (PARAGRAPH + '\n') * 30))
        self.assertLessEqual(len(shown), MAX_ANSWER_CHARS + 60)
        self.assertTrue(shown.endswith(PARAGRAPH + '\n…'))

    def test_holds_only_text_that_stands_in_the_section(self):
        part = section('/orchin', 'Суралцах орчин', 'Уншлагын танхим')
        self.assertTrue(holds(part, '• ' + PARAGRAPH + ' [1]'.replace(' [1]', '')))
        self.assertFalse(holds(part, PARAGRAPH + '\nӨөр хуудасны өөр нэг урт өгүүлбэр энд байна.'))
        self.assertFalse(holds(part, 'Богино'))


class CutterTests(unittest.TestCase):
    def test_a_figure_stays_with_its_caption_and_card_numbers_go(self):
        lines = cutter.clean_lines('3270+\nном, сурах бичиг\n12\nСалбар нэгж\n01\nНэг\n02\nХоёр\n09\nЕс\n10\nАрав\nNEW\nтохижилт')
        self.assertEqual(lines, ['3270+ ном, сурах бичиг', '12 Салбар нэгж', 'Нэг', 'Хоёр', 'Ес', 'Арав'])

    def test_a_figure_after_a_few_numbered_cards_is_still_a_figure(self):
        self.assertEqual(cutter.clean_lines('01\nНэг\n02\nХоёр\n3\nлаборатори'), ['Нэг', 'Хоёр', '3 лаборатори'])

    def test_navigation_buttons_and_staff_mobiles_go(self):
        lines = cutter.clean_lines('Нүүр Тэнхимүүд Роботын тэнхим\nБуцах\nНэвтрэх\nУтас 99112233\nИмэйл robot@school.example\n'
                                   'Сургуулийн утас 7577-0000\n2026 оны есдүгээр сарын 12 92 үзсэн')
        self.assertEqual(lines, ['Имэйл robot@school.example', 'Сургуулийн утас 7577-0000', '2026 оны есдүгээр сарын 12'])

    def test_a_mobile_under_a_figure_is_dropped_with_it(self):
        self.assertEqual(cutter.clean_lines('3\nУтас: 99112233\nДараагийн мөр'), ['Дараагийн мөр'])

    def test_headings_with_html_entities_are_read_as_text(self):
        self.assertEqual(cutter.html_headings('<h2>Сургалт &ndash; судалгаа</h2><h3>&laquo;Нээлттэй&raquo; өдөр</h3>'),
                         [(2, 'Сургалт – судалгаа'), (3, '«Нээлттэй» өдөр')])

    def test_a_figure_is_not_joined_to_a_heading(self):
        self.assertEqual(cutter.clean_lines('2014\nҮүсгэн байгуулагдсан\n' + PARAGRAPH, ['Үүсгэн байгуулагдсан']),
                         ['Үүсгэн байгуулагдсан', PARAGRAPH])

    def test_headings_of_the_html_cut_the_text_and_a_contact_heading_ends_it(self):
        html = ('<nav><h3>Цэс</h3></nav><h1>Суралцах орчин</h1><h2>Танхимууд</h2><h3>Уншлагын танхим</h3>'
                '<h3>Лекцийн танхим</h3><h2>Спорт</h2><h3>Холбоо барих</h3><footer><h3>Холбоосууд</h3></footer>')
        headings = cutter.html_headings(html)
        self.assertEqual(headings, [(1, 'Суралцах орчин'), (2, 'Танхимууд'), (3, 'Уншлагын танхим'),
                                    (3, 'Лекцийн танхим'), (2, 'Спорт'), (3, 'Холбоо барих')])
        lines = ['Суралцах орчин', PARAGRAPH, 'I. ОРЧИН', 'Танхимууд', 'Уншлагын танхим', 'Чимээгүй. ' + PARAGRAPH,
                 'Лекцийн танхим', 'Том. ' + PARAGRAPH, 'Спорт', 'Заал. ' + PARAGRAPH, 'Холбоо барих',
                 'Эрхлэгч З.Наран', 'Имэйл naran@school.example']
        parts = {part['heading']: part for part in cutter.cut_by_headings('Суралцах орчин', lines, headings)}
        self.assertEqual(list(parts), ['Суралцах орчин', 'Танхимууд', 'Уншлагын танхим', 'Лекцийн танхим', 'Спорт'])
        self.assertEqual(parts['Танхимууд']['label'], 'I. ОРЧИН')
        self.assertEqual(parts['Танхимууд']['text'], 'Уншлагын танхим\nЧимээгүй. ' + PARAGRAPH + '\n\nЛекцийн танхим\nТом. ' + PARAGRAPH)
        self.assertEqual(parts['Лекцийн танхим']['parent'], 'Танхимууд')
        self.assertEqual(parts['Спорт']['text'], 'Заал. ' + PARAGRAPH)          # nothing of the contact block
        self.assertIsNone(cutter.cut_by_headings('Суралцах орчин', lines, [(1, 'Суралцах орчин'), (2, 'Спорт')]))

    def test_without_html_headings_short_capitalised_lines_before_a_paragraph_cut_the_text(self):
        lines = ['Эрхэм зорилго', PARAGRAPH, 'Оюутны тоо', 'Нийт 128 оюутан суралцаж байна. ' + PARAGRAPH,
                 'Зорилго, зорилт', 'Үндсэн зорилго', PARAGRAPH, 'Холбоо барих', 'Эрхлэгч З.Наран',
                 'Имэйл naran@school.example', 'Дараах хаягаар бидэнтэй холбогдож, асуултаа илгээх боломжтой байгаа шүү.']
        parts = cutter.cut_by_shape('Роботын тэнхим', lines)
        self.assertEqual([part['heading'] for part in parts], ['Эрхэм зорилго', 'Оюутны тоо', 'Үндсэн зорилго'])
        self.assertEqual(parts[1]['text'], 'Нийт 128 оюутан суралцаж байна. ' + PARAGRAPH)   # no «Зорилго, зорилт» tail
        self.assertFalse(any('Наран' in part['text'] for part in parts))


class StoredAnswerWordingTests(unittest.TestCase):
    ANSWER = ('Гурван хөтөлбөр бий:\n• Алтай — 5–7 хоногийн аялал.\n• Хангай — соёл, түүхийг танилцуулах хөтөлбөр.\n'
              'Бэлтгэл хөтөлбөр: төгсөгчдөд зориулсан сургалт.\n\n(Эх сурвалж: сургуулийн сайтын «Жишээ» хуудас.)')

    def test_the_list_item_that_opens_with_the_asked_name_is_repeated_on_top(self):
        shown = named_first('Хангай хөтөлбөр гэж юу вэ?', self.ANSWER)
        self.assertTrue(shown.startswith('Хангай — соёл, түүхийг танилцуулах хөтөлбөр.\n\nГурван хөтөлбөр бий:'))
        self.assertIn('• Хангай — соёл', shown)
        self.assertTrue(shown.endswith('(Эх сурвалж: сургуулийн сайтын «Жишээ» хуудас.)'))

    def test_a_plain_line_is_moved_not_repeated(self):
        shown = named_first('Бэлтгэл хөтөлбөрийн талаар', self.ANSWER)
        self.assertTrue(shown.startswith('Бэлтгэл хөтөлбөр: төгсөгчдөд зориулсан сургалт.\n\nГурван хөтөлбөр бий:'))
        self.assertEqual(shown.count('Бэлтгэл хөтөлбөр:'), 1)

    def test_the_line_must_open_as_the_asked_name_does(self):
        # «Хангай» is one of the asked words, but the asked name opens with another word.
        self.assertEqual(named_first('Монгол хангай хөтөлбөр гэж юу вэ?', self.ANSWER), self.ANSWER)

    def test_other_questions_and_answers_without_such_a_line_are_left(self):
        self.assertEqual(named_first('Ямар хөтөлбөрүүд байдаг вэ?', self.ANSWER), self.ANSWER)
        self.assertEqual(named_first('Говь хөтөлбөр гэж юу вэ?', self.ANSWER), self.ANSWER)
        self.assertEqual(named_first('Хангай хөтөлбөр гэж юу вэ?', 'Нэг мөртэй хариулт.'), 'Нэг мөртэй хариулт.')

    def test_a_no_always_stays_and_a_yes_stays_under_any_yes_or_no_wording(self):
        no = 'Үгүй. Гэхдээ түрээсийн байр зуучилна.'
        for query in ('Дотуур байрны талаар', 'Дотуур байр гэж юу вэ?', 'Дотуур байр бий юу, хэдэн төгрөг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(drop_yes(query, no), no)
        yes = 'Тийм. 400 м² талбай бүхий хоолны газар бий.'
        for query in ('Хоолны газар бий юу, хэдэн суудалтай вэ?', 'Хоолны газар байгаа биз дээ?',
                      'Хоолны газар байдаг уу? Баярлалаа', 'hoolnii gazar bga yu'):
            with self.subTest(query=query):
                self.assertEqual(drop_yes(query, yes), yes)

    def test_a_header_that_only_opens_a_list_is_not_moved(self):
        answer = 'Сургууль дараах хөтөлбөртэй.\nХангай хөтөлбөр:\n• 7–30 хоног\n• Зардлыг сургууль хариуцна'
        self.assertEqual(named_first('Хангай хөтөлбөр гэж юу вэ?', answer), answer)

    def test_a_stray_yes_goes_only_under_a_question_that_is_not_yes_or_no(self):
        answer = 'Тийм. 400 м² талбай бүхий хоолны газар бий.'
        self.assertEqual(drop_yes('Хоолны газрын талаар', answer), '400 м² талбай бүхий хоолны газар бий.')
        self.assertEqual(drop_yes('Хоолны газар байдаг уу?', answer), answer)
        self.assertEqual(drop_yes('Хоолны газар байгаа юу?', answer), answer)
        self.assertEqual(drop_yes('Хоолны газар гэж юу вэ?', 'Тийм.'), 'Тийм.')

    def test_present_applies_both_to_a_stored_answer_only(self):
        stored = present(dict(query='Хангай хөтөлбөр гэж юу вэ?', answer='Тийм. ' + self.ANSWER, message='',
                              answer_kind='official_website_snapshot'))
        self.assertTrue(stored['answer'].startswith('Хангай — соёл'))
        table = present(dict(query='Хангай хөтөлбөр гэж юу вэ?', answer=self.ANSWER, message='',
                             answer_kind='reception_table_lookup'))
        self.assertTrue(table['answer'].startswith('Гурван хөтөлбөр бий:'))


class ChatRouteTests(unittest.TestCase):
    """The section step inside the chat route, behind a fake router and a fake search."""
    SENTENCE = 'Сургалтын орчны ерөнхий танилцуулга энд байна.'

    class Policy:
        enabled = True

        def __init__(self, reason):
            self.reason = reason

        def route(self, db, query, allow_draft=False):
            return dict(query=query, route='E', package_id='package1', answer=None, citations=[], reason_code=self.reason,
                        reason_codes=[], clarification=None, exact_matches=[], generated=False, llm_calls=0,
                        message='Олдсонгүй.', answer_kind=None)

    class Retriever:
        def status(self):
            return dict(available=True, corpus_id='corpus1')

        def search(self, query, limit=4):
            return dict(candidates=[], corpus_id='corpus1', backend='test')

    class Generator:
        def status(self):
            return dict(available=True)

    def chat(self, reason='no_supported_question_match', sections=None):
        from faq_intent import FaqIntents
        from rag_runtime import ChatRAG
        chat = ChatRAG('.', self.Policy(reason), self.Retriever(), self.Generator(), reception=ReceptionAnswerPath())
        chat.faq_intents = FaqIntents(enabled=False)
        chat.sections = index() if sections is None else sections
        return chat

    def test_an_unanswered_describing_question_gets_the_named_section(self):
        result = self.chat().route('content.db', 'Нийтийн хоолны газрын талаар')
        self.assertEqual(result['route'], 'C')
        self.assertEqual(result['answer_kind'], 'website_section')
        self.assertTrue(result['answer'].startswith('Нийтийн хоолны газар (Суралцах орчин)\nХоолны цэсийг сар бүр баталдаг.'))
        self.assertEqual(result['citations'][0]['source_url_or_filename'], SITE + '/orchin')
        self.assertEqual(result['citations'][0]['locator'], 'Нийтийн хоолны газар')
        self.assertEqual(result['rag']['corpus_id'], 'corpus1')
        self.assertEqual(result['llm_calls'], 0)
        self.assertFalse(result['generated'])
        self.assertNotIn('referral', {key for key, value in result.items() if value})

    def test_the_section_reply_can_be_recalled_for_listening_also_after_a_stop_of_the_router(self):
        for reason in ('no_supported_question_match', 'missing_entity'):
            with self.subTest(reason=reason):
                chat = self.chat(reason)
                result = chat.route('content.db', 'Нийтийн хоолны газрын талаар')
                self.assertEqual(result['answer_kind'], 'website_section')
                recalled = chat.recall(result['response_id'], 'Нийтийн хоолны газрын талаар', 'package1', False)
                self.assertEqual(recalled['answer'], result['answer'])

    def test_a_question_that_names_no_section_stays_unanswered_with_where_to_ask(self):
        for query in ('Нийтийн хоолны газар ямар цагаар ажилладаг вэ?', 'Дотуур байр байдаг уу?',
                      'Нийтийн хоолны газарт карт уншуулж болох уу?'):
            with self.subTest(query=query):
                result = self.chat().route('content.db', query)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['route'], 'E')

    def test_a_refusal_with_a_reason_of_its_own_is_never_replaced(self):
        chat = self.chat()
        for reason in ('future_admission_round_not_published', 'personal_record_outside_scope', 'reception_post_phone',
                       'cooperation_entity_conflict', 'live_status_not_supported'):
            with self.subTest(reason=reason):
                refused = dict(query='Нийтийн хоолны газрын талаар', route='E', answer=None, reason_code=reason,
                               message='Татгалзав.', citations=[])
                self.assertIs(chat._section_answer(refused, refused['query']), refused)
                self.assertIsNone(refused['answer'])
                self.assertEqual(refused['reason_code'], reason)

    def test_an_extract_gives_way_to_the_whole_section_of_a_page(self):
        chat = self.chat()
        extract = dict(query='Нийтийн хоолны газрын талаар', route='C', answer='Өөр хуудасны нэг өгүүлбэр. [1]',
                       answer_kind='rag_generated', reason_code='source_grounded_generation', citations=[{}],
                       rag=dict(corpus_id='corpus1', llm_calls=0))
        shown = chat._section_answer(extract, extract['query'])
        self.assertEqual(shown['answer_kind'], 'website_section')
        self.assertEqual(shown['rag']['section']['replaced']['answer_kind'], 'rag_generated')

    def test_an_extract_stays_when_the_section_is_too_long_or_is_a_news_item_that_does_not_hold_it(self):
        chat = self.chat()
        for query in ('Спорт, хоол, хөгжлийн талаар', 'Намрын наадмын талаар'):
            with self.subTest(query=query):
                extract = dict(query=query, route='C', answer='Өөр хуудасны нэг урт өгүүлбэр энд байна. [1]',
                               answer_kind='rag_generated', reason_code='source_grounded_generation', citations=[{}])
                self.assertEqual(chat._section_answer(extract, query)['answer_kind'], 'rag_generated')
        held = dict(query='Намрын наадмын талаар', route='C', answer='Намрын наадам амжилттай боллоо. [1]',
                    answer_kind='rag_generated', reason_code='source_grounded_generation', citations=[{}])
        self.assertEqual(chat._section_answer(held, held['query'])['answer_kind'], 'website_section')

    def test_stored_table_and_clarifying_replies_are_left(self):
        chat = self.chat()
        for kind, route, answer in (('official_website_snapshot', 'B', 'Хадгалсан хариулт.'),
                                    ('reception_table_lookup', 'C', 'Хүснэгтийн хариулт.')):
            with self.subTest(kind=kind):
                given = dict(query='Нийтийн хоолны газрын талаар', route=route, answer=answer, answer_kind=kind,
                             reason_code='official_website_stored_answer', citations=[])
                self.assertEqual(chat._section_answer(given, given['query'])['answer'], answer)
        asking = dict(query='Нийтийн хоолны газрын талаар', route='D', answer=None, reason_code='select_supported_question',
                      clarification=dict(kind='choose', question='Аль нь вэ?', options=[]), citations=[])
        self.assertIsNone(chat._section_answer(asking, asking['query'])['answer'])

    def test_only_a_what_is_question_that_names_a_page_section_goes_before_a_mapped_stored_answer(self):
        chat = self.chat()
        self.assertEqual(chat._named_page_section('Нийтийн хоолны газрын талаар')['section'].heading, 'Нийтийн хоолны газар')
        self.assertIsNotNone(chat._named_page_section('Уншлагын танхим гэж юу вэ?'))
        self.assertIsNone(chat._named_page_section('Хоолны газар байдаг уу?'))                 # a stored «Тийм. …» is more direct
        self.assertIsNone(chat._named_page_section('Намрын наадмын талаар'))                   # a news item
        self.assertIsNone(chat._named_page_section('Od Internet компанитай хамтын ажиллагааны талаар'))   # one word outside the names
        self.assertIsNone(chat._named_page_section('Роботын тэнхимийн талаар'))                # names a page, not a section
        self.assertIsNone(chat._named_page_section('Суралцах орчны талаар'))                   # the page's opening text
        self.assertIsNone(chat._named_page_section('Спорт, хоол, хөгжлийн талаар'))            # too long to show whole

    def test_the_named_section_is_shown_at_once_instead_of_a_mapped_stored_answer(self):
        # Not only «give up the stored answer»: the website path may end in a reply no later step replaces.
        from faq_intent import FaqIntents
        chat = self.chat()
        chat.faq_intents = FaqIntents(enabled=True)
        chat.faq_intents.enabled = True         # without intents of its own it switches itself off
        unanswered = self.Policy('no_supported_question_match').route('content.db', 'Нийтийн хоолны газрын талаар')
        shown = chat._faq_intent_answer('content.db', 'Нийтийн хоолны газрын талаар', unanswered, False)
        self.assertEqual(shown['answer_kind'], 'website_section')
        self.assertTrue(shown['response_id'])
        self.assertIsNone(chat._faq_intent_answer('content.db', 'Хоолны газар байдаг уу?',
                                                  self.Policy('no_supported_question_match').route('content.db', 'x'), False))

    def test_without_sections_for_the_served_corpus_nothing_changes(self):
        result = self.chat(sections=SectionIndex()).route('content.db', 'Нийтийн хоолны газрын талаар')
        self.assertIsNone(result['answer'])
        chat = self.chat()
        chat.sections = None        # the stored file, if any, was cut from another corpus than the one served here
        self.assertIsNone(chat.route('content.db', 'Нийтийн хоолны газрын талаар')['answer'])


if __name__ == '__main__':
    unittest.main()
