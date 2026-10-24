import unittest

from CORE.website_corpus import PageParser, STRUCTURAL_SPANS_VERSION, structural_spans


class WebsiteStructureTests(unittest.TestCase):
    def extract(self, html):
        parser = PageParser()
        parser.feed(html)
        return parser.result()['text']

    def partition(self, html):
        text = self.extract(html)
        spans = structural_spans(html, text)
        self.assertTrue(spans)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        self.assertEqual(''.join(text[start:end] for start, end in spans), text)
        for left, right in zip(spans, spans[1:]):
            self.assertEqual(left[1], right[0])
        for start, end in spans:
            self.assertLess(start, end)
            if start:
                self.assertEqual(text[start - 1], '\n')
        return text, spans, [text[start:end].strip() for start, end in spans]

    def test_timeline_row_keeps_sibling_year_and_paragraph_outside_statistic_section(self):
        html = '''<main><section><h1>Хөгжлийн зам</h1><div>99</div><div>Нийт үйл явдал</div></section>
        <section><div><div><div><span>2041</span></div><div><h3>Эхний үйл явдал</h3>
        <p>Эхний хамт олон үйл ажиллагаагаа эхлүүлсэн.</p></div></div>
        <div><div><span>2042</span></div><div><h3>Дараагийн үйл явдал</h3>
        <p>Хамтын ажиллагааны шинэ төв нээгдсэн.</p></div></div></div></section></main>'''
        _, _, pieces = self.partition(html)
        first = next(piece for piece in pieces if 'Эхний үйл явдал' in piece)
        self.assertTrue(first.startswith('2041\nЭхний үйл явдал'))
        self.assertNotIn('99', first)
        self.assertNotIn('2042', first)

    def test_facility_card_retains_badge_conditions_and_list_but_not_previous_room_list(self):
        html = '''<main><section><h2>Өрөөнүүд</h2><ol><li>01 А өрөө</li><li>02 Б өрөө</li></ol></section>
        <section><div><article><h3>Унших төв</h3><p>Бүртгэлтэй үед ашиглана.</p>
        <ul><li>Хэрэв захиалгагүй бол хүлээнэ.</li><li>Харин захиалгатай бол шууд орно.</li></ul>
        <div>720+</div><div>ширхэг материал</div></article><article><h3>Спортын төв</h3>
        <p>Хичээлийн дараа ашигладаг.</p><div>40</div><div>суудал</div></article></div></section></main>'''
        _, _, pieces = self.partition(html)
        card = next(piece for piece in pieces if 'Унших төв' in piece)
        self.assertTrue(card.startswith('Унших төв\n'))
        self.assertIn('720+\nширхэг материал', card)
        self.assertIn('Хэрэв захиалгагүй', card)
        self.assertIn('Харин захиалгатай', card)
        self.assertNotIn('А өрөө', card)
        self.assertNotIn('Спортын төв', card)

    def test_repeated_card_feature_list_stays_with_its_own_heading(self):
        html = '''<main><section><div>
        <div><h3>Арга А</h3><p>Эхний арга нь явцыг хянадаг.</p><ul><li>Явц</li><li>Зөвлөгөө</li></ul></div>
        <div><h3>Арга Б</h3><p>Дараагийн арга нь үр дүнг үнэлдэг.</p><ul><li>Үр дүн</li><li>Оролцоо</li></ul></div>
        </div></section><section><h2>Өөр сэдэв</h2><p>Тусдаа сэдэв.</p></section></main>'''
        _, _, pieces = self.partition(html)
        second = next(piece for piece in pieces if 'Арга Б' in piece)
        self.assertTrue(second.startswith('Арга Б\n'))
        self.assertNotIn('Зөвлөгөө', second)
        self.assertTrue(second.endswith('Үр дүн\nОролцоо'))
        self.assertNotIn('Өөр сэдэв', second)

    def test_shared_section_year_or_condition_vetoes_card_splitting(self):
        for prefix in ('<h2>2043 оны нөхцөл</h2>',
                       '<h2>Нийтлэг нөхцөл</h2><p>Зөвхөн бүртгэлтэй бол ашиглана.</p>',
                       '<h2>Common scope</h2><p>Only registered visitors may enter.</p>'):
            with self.subTest(prefix=prefix):
                html = '<main><section>' + prefix + '''<div><div><h3>А төв</h3><p>Тайлбар А.</p></div>
                <div><h3>Б төв</h3><p>Тайлбар Б.</p></div></div></section></main>'''
                text, spans, _ = self.partition(html)
                self.assertEqual(spans, [(0, len(text))])

    def test_company_pronoun_chain_and_conditional_are_not_split_at_paragraphs(self):
        html = '''<main><section><h2>Partner Example Ltd.</h2><p>Example компани үйлчилгээг үзүүлдэг.</p>
        <p>Тус компанитай хамтран ажилладаг.</p><p>Хэрэв хүсэлт гаргавал нэмэлт үйлчилгээ авна.</p>
        <p>Мөн холбогдох нөхцөлийг мөрдөнө.</p></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_nested_sections_preserve_outer_common_year_and_condition(self):
        html = '''<main><section><h2>2044 оны нийтлэг нөхцөл</h2><p>Хэрэв бүртгэлтэй бол ашиглана.</p>
        <section><h3>А үйлчилгээ</h3><p>Эхний тайлбар.</p></section>
        <section><h3>Б үйлчилгээ</h3><p>Дараагийн тайлбар.</p></section></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_shared_prose_implicit_eligibility_vetoes_card_splitting(self):
        html = '''<main><section><h2>Бэлтгэл хөтөлбөр</h2>
        <p>Дэвшин суралцах шаардлагыг бүрэн хангасан төгсөгчдөд зориулна.</p><div>
        <div><h3>А хичээл</h3><p>Эхний хичээлийн тайлбар.</p></div>
        <div><h3>Б хичээл</h3><p>Дараагийн хичээлийн тайлбар.</p></div>
        </div></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_shared_negative_heading_vetoes_card_splitting(self):
        html = '''<main><section><h2>Одоогоор ажиллахгүй үйлчилгээ</h2><div>
        <div><h3>А үйлчилгээ</h3><p>Эхний тайлбар.</p></div>
        <div><h3>Б үйлчилгээ</h3><p>Дараагийн тайлбар.</p></div></div></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_shared_arbitrary_subject_and_spelled_out_grade_veto_card_splitting(self):
        for heading in ('Коллежийн ахлах ангийн суралцагчид', 'Аравдугаар ангийн сурагчид'):
            with self.subTest(heading=heading):
                html = '<main><section><h2>' + heading + '''</h2><div>
                <div><h3>А үйлчилгээ</h3><p>Эхний тайлбар.</p></div>
                <div><h3>Б үйлчилгээ</h3><p>Дараагийн тайлбар.</p></div></div></section></main>'''
                text, spans, _ = self.partition(html)
                self.assertEqual(spans, [(0, len(text))])

    def test_main_shared_arbitrary_subject_vetoes_section_cuts(self):
        html = '''<main><h1>Коллежийн ахлах ангийн суралцагчид</h1>
        <section><h2>А үйлчилгээ</h2><p>Эхний тайлбар.</p></section>
        <section><h2>Б үйлчилгээ</h2><p>Дараагийн тайлбар.</p></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_bare_div_or_span_shared_subject_also_vetoes_inner_cuts(self):
        for label in ('<div>Коллежийн ахлах ангийн суралцагчид</div>',
                      '<span>Аравдугаар ангийн сурагчид</span>'):
            with self.subTest(label=label):
                cards = '''<div><div><h3>А үйлчилгээ</h3><p>Эхний тайлбар.</p></div>
                <div><h3>Б үйлчилгээ</h3><p>Дараагийн тайлбар.</p></div></div>'''
                main_html = '<main>' + label + '<section>' + cards + '</section></main>'
                text, spans, _ = self.partition(main_html)
                self.assertEqual(spans, [(0, len(text))])
                section_html = '<main><section>' + label + cards + '</section></main>'
                text, spans, _ = self.partition(section_html)
                self.assertEqual(spans, [(0, len(text))])

    def test_main_common_year_outside_sections_vetoes_all_section_and_card_cuts(self):
        html = '''<main><h1>2045 оны үйлчилгээ</h1><section><h2>А хүрээ</h2><div>
        <div><h3>А үйлчилгээ</h3><p>Эхний тайлбар.</p></div>
        <div><h3>Б үйлчилгээ</h3><p>Дараагийн тайлбар.</p></div></div></section>
        <section><h2>Б хүрээ</h2><p>Өөр үйлчилгээ.</p></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_unicode_entities_inline_markup_and_whitespace_map_without_substring_search(self):
        html = '''<html><head><title>Ignored</title></head><body><nav>Гаднах цэс</nav><main>
        <section><h2>Үндсэн &amp; сэдэв</h2><p>e\u0301 <b>Монгол</b><span>хэл</span> &lt; утга.</p></section>
        <section><h2>Өөр сэдэв</h2><p>Өөр утга.</p></section></main></body></html>'''
        text, _, pieces = self.partition(html)
        self.assertIn('é Монгол хэл < утга.', text)
        self.assertNotIn('Гаднах цэс', text)
        self.assertEqual(len(pieces), 2)

    def test_missing_heading_or_mixed_siblings_does_not_infer_cards_from_short_lines(self):
        html = '''<main><section><h2>Жагсаалт</h2><div><div><span>А</span><p>Урт тайлбар А.</p></div>
        <div><span>Б</span><p>Урт тайлбар Б.</p></div></div></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_parent_direct_context_is_not_discarded_by_repeated_card_detection(self):
        html = '''<main><section><h2>Нийтлэг сэдэв</h2><div>Хамтын нэр
        <div><h3>А</h3><p>Эхний тайлбар.</p></div><div><h3>Б</h3><p>Хоёр дахь тайлбар.</p></div>
        </div></section></main>'''
        text, spans, _ = self.partition(html)
        self.assertEqual(spans, [(0, len(text))])

    def test_mismatch_unsupported_and_malformed_html_fail_closed(self):
        good = '<main><section><h2>Сэдэв</h2><p>Тайлбар.</p></section></main>'
        self.assertEqual(structural_spans(good, self.extract(good) + '!'), [])
        self.assertEqual(structural_spans('<p>Текст.</p>', 'Текст.'), [])
        malformed = '<main><section><h2>Сэдэв</h2><p>Тайлбар.</section></p></main>'
        self.assertEqual(structural_spans(malformed, self.extract(malformed)), [])
        for html, text in ((None, 'text'), (good, None), ('', ''), (b'<main/>', 'text')):
            self.assertEqual(structural_spans(html, text), [])
        self.assertEqual(STRUCTURAL_SPANS_VERSION, 'canonical-dom-fences-v1')


if __name__ == '__main__':
    unittest.main()
