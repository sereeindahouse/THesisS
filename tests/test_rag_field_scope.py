"""Constructed field-scope regressions; saved wording, no inference or gold score."""
import unittest

from evidence_contract import evidence_units, resolve_evidence_selection
from rag_runtime import refine_evidence_selection
from source_fields import ambiguity, closed_field_selection_query, field_evidence_requirements, missing_field_evidence


class NamedLibraryUseYearTests(unittest.TestCase):
    fresh = 'Номын сангийн Koha-г хэдэн оноос ашиглаж эхэлсэн, нэг оюутанд хэдэн ном ногддог, нийт хэдэн номтой вэ?'
    expected = ['library_stock_total', 'library_software_start_year', 'library_per_student_ratio']

    def test_frozen_fresh_wording_requires_all_three_explicit_facets(self):
        fields = field_evidence_requirements(self.fresh)
        self.assertEqual([f['name'] for f in fields], self.expected)
        self.assertEqual(fields[1]['program_name'], 'koha')
        # Invented values verify roles rather than matching school answer values.
        software = 'Koha программыг 2003 оноос нэвтрүүлэн ашиглаж байна.'
        ratio = 'Нэг оюутанд 3.4–8.1 ном ногдож байна.'
        total = '4200+\nном, сурах бичиг'
        self.assertEqual(missing_field_evidence(fields, [software, ratio]), ['library_stock_total'])
        self.assertEqual(missing_field_evidence(fields, [software, total]), ['library_per_student_ratio'])
        self.assertEqual(missing_field_evidence(fields, [ratio, total]), ['library_software_start_year'])
        self.assertEqual(missing_field_evidence(fields, [software, ratio, total]), [])

    def test_generic_latin_names_and_case_suffixes_are_not_hardcoded(self):
        for name, suffix, date_verb in [('LumaShelf', 'ийг', 'хэдэн оноос ашиглаж эхэлсэн'),
                                        ('OpenShelf', 'ыг', 'хэзээнээс хэрэглэж эхэлсэн'),
                                        ('BookOS', 'г', 'хэдэн онд нэвтрүүлсэн')]:
            query = f'Номын сангийн {name}-{suffix} {date_verb}, нэг оюутанд хэдэн ном ногддог, нийт хэдэн номтой вэ?'
            with self.subTest(query=query):
                fields = field_evidence_requirements(query)
                self.assertEqual([f['name'] for f in fields], self.expected)
                self.assertEqual(fields[1]['program_name'], name.casefold())
                self.assertEqual(missing_field_evidence(fields, [f'{name} программыг 2003 оноос ашиглаж байна.',
                    'Нэг оюутанд 3–8 ном ногдож байна.', '4200 номтой']), [])

    def test_other_named_program_cannot_supply_requested_software_year(self):
        fields = field_evidence_requirements(self.fresh)
        self.assertEqual(missing_field_evidence(fields, ['OtherShelf программыг 2003 оноос ашиглаж байна.',
            'Нэг оюутанд 3–8 ном ногдож байна.', '4200 номтой']), ['library_software_start_year'])

    def test_no_default_program_from_library_or_latin_name_alone(self):
        for query in ['Номын санг хэдэн оноос ашиглаж эхэлсэн, нийт хэдэн номтой вэ?',
                      'Номын сан хэдэн оноос ажиллаж эхэлсэн, нийт хэдэн номтой вэ?',
                      'LumaShelf-г хэдэн оноос ашиглаж эхэлсэн, нийт хэдэн номтой вэ?',
                      'Номын сангийн LumaShelf-ийн нэр ба нийт номын тоог хэл.']:
            with self.subTest(query=query):
                self.assertEqual(field_evidence_requirements(query), [])

    def test_unknown_conjoined_name_is_clarified_without_replacing_its_suffix(self):
        query = 'Номын сангийн нийт номын тоо болон WrongShelf-г хэдэн оноос ашиглаж эхэлсэн бэ?'
        sources = [dict(text='Номын сан\nLumaShelf олон улсын програм\nLumaShelf программыг 2003 оноос ашиглаж байна.')]
        result = ambiguity(query, sources)
        self.assertIsNotNone(result)
        self.assertIn('WrongShelf', result[0])
        self.assertEqual(result[1], [query.replace('WrongShelf', 'LumaShelf')])

    def test_partial_library_fields_never_authorize_unknown_conjunction_pruning(self):
        for query in [self.fresh,
                      self.fresh.rstrip('?') + ', мөн номын санчийн нэрийг хэл?',
                      'Номын сангийн LumaShelf-г хэдэн оноос ашиглаж эхэлсэн, нийт хэдэн номтой, хаана байрладаг вэ?']:
            with self.subTest(query=query):
                fields = field_evidence_requirements(query)
                self.assertTrue(fields)
                self.assertFalse(closed_field_selection_query(query, fields))


class SinglePurposeScopeTests(unittest.TestCase):
    monitoring = 'Мониторинг\nӨдөр тутмын үйл ажиллагааны хэрэгжилтийг хянаж, дэмжин зөвлөх зорилготой.'
    evaluation = 'Үнэлгээ\nЗорилтын биелэлтийг тодорхой хугацааны давтамжтай үнэлж, шинэчлэн сайжруулах зорилгоор хийнэ.'
    observed = 'Чанарын баталгаажуулалтын хуудсанд мониторинг ямар зорилготой гэж тайлбарласан бэ?'

    def refine(self, query, texts):
        sources = [dict(source_id=str(i), text=text, url='https://example.edu/quality',
                        version=1, text_scope='main_element', start_offset=i*1000,
                        end_offset=i*1000+len(text)) for i, text in enumerate(texts)]
        units = evidence_units(sources)
        roots = [u['unit_id'] for u in units]
        resolved = resolve_evidence_selection(query, roots, units, max_claims=6)
        self.assertTrue(resolved['accepted'], resolved)
        return refine_evidence_selection(query, roots, units, resolved), resolved

    def test_exact_single_purpose_grammars_activate_one_definition(self):
        for query, subject in [(self.observed, 'monitoring'),
                               ('Мониторингийн зорилго юу вэ?', 'monitoring'),
                               ('Эхэд үнэлгээ ямар зорилготой гэж тодорхойлсон бэ?', 'evaluation'),
                               ('Үнэлгээний зорилгыг тайлбарла.', 'evaluation')]:
            with self.subTest(query=query):
                fields = field_evidence_requirements(query)
                self.assertEqual([f['name'] for f in fields], [subject+'_definition'])
                self.assertTrue(closed_field_selection_query(query, fields))

    def test_opposing_subject_cannot_supply_missing_purpose(self):
        for query, wanted, other in [(self.observed, 'monitoring_definition', self.evaluation),
                                     ('Үнэлгээний зорилго юу вэ?', 'evaluation_definition', self.monitoring)]:
            with self.subTest(query=query):
                self.assertEqual(missing_field_evidence(field_evidence_requirements(query), other), [wanted])

    def test_other_subject_predicate_cannot_leak_across_header_or_sentence(self):
        fields = field_evidence_requirements('Мониторингийн зорилго юу вэ?')
        for text in ['Мониторинг\nТайлбар удахгүй нэмэгдэнэ.\n'+self.evaluation,
                      'Мониторинг нь тайлбар хүлээгдэж байна. Үнэлгээ нь үр дүнг сайжруулах зорилготой.']:
            with self.subTest(text=text):
                self.assertEqual(missing_field_evidence(fields, text), ['monitoring_definition'])

    def test_generic_refinement_removes_only_opposing_complete_purpose_root(self):
        for query, expected in [(self.observed, self.monitoring),
                                 ('Үнэлгээний зорилго юу вэ?', self.evaluation)]:
            with self.subTest(query=query):
                (after, diagnostic), before = self.refine(query, [self.monitoring, self.evaluation])
                self.assertEqual(len(before['claims']), 2)
                self.assertEqual([c['text'] for c in after['claims']], [expected])
                self.assertEqual(diagnostic['reason'], 'closed_fields_complete_subset')

    def test_opposing_purpose_after_any_connector_cannot_replace_true_root(self):
        for query, name, other, true_text in [
            ('Мониторингийн зорилго юу вэ?', 'Мониторинг', 'Үнэлгээ', self.monitoring),
            ('Үнэлгээний зорилго юу вэ?', 'Үнэлгээ', 'Мониторинг', self.evaluation)]:
            for connector in ['; ', ', ', ' — ', ' мөн ', ' / ', ' (', '\n', '. ']:
                mixed = name+' нь дараа тайлбарлагдана'+connector+other+' нь үр дүнг сайжруулах зорилготой.'
                with self.subTest(query=query, connector=connector):
                    fields = field_evidence_requirements(query)
                    self.assertEqual(missing_field_evidence(fields, mixed), [fields[0]['name']])
                    (after, _), before = self.refine(query, [mixed, true_text])
                    self.assertIn(true_text, [c['text'] for c in after['claims']])

    def test_reported_activity_is_not_an_explicit_purpose(self):
        for query, activity, true_text in [
            ('Мониторингийн зорилго юу вэ?', 'Мониторинг\nӨчигдөр баг бүртгэлийн мэдээллийг хянасан.', self.monitoring),
            ('Үнэлгээний зорилго юу вэ?', 'Үнэлгээ\nӨчигдөр баг шинэ талбайг үнэлж дууссан.', self.evaluation)]:
            with self.subTest(query=query):
                fields = field_evidence_requirements(query)
                self.assertEqual(missing_field_evidence(fields, activity), [fields[0]['name']])
                (after, _), before = self.refine(query, [activity, true_text])
                self.assertIn(true_text, [c['text'] for c in after['claims']])

    def test_ambiguous_opposing_object_is_conservatively_not_certified(self):
        fields = field_evidence_requirements('Мониторингийн зорилго юу вэ?')
        ambiguous = 'Мониторинг нь үнэлгээг дэмжин сайжруулах зорилготой.'
        self.assertEqual(missing_field_evidence(fields, ambiguous), ['monitoring_definition'])
        explicit = 'Мониторингийн зорилго нь өдөр тутмын үйл ажиллагааг хянах юм.'
        self.assertEqual(missing_field_evidence(fields, explicit), ['monitoring_definition'])

    def test_no_requested_subject_root_can_be_removed_by_a_false_purpose_marker(self):
        for bad in ['Мониторинг\nЗорилго нь дараа тодорхой болно.',
                    'Мониторинг\nЗорилго нь.',
                    'Мониторинг\nӨчигдөр баг «зорилго нь юу вэ» гэсэн асуулт хэлэлцсэн.',
                    'Мониторинг\n«Зорилготой» гэсэн үгийг дараа тайлбарлана.']:
            with self.subTest(text=bad):
                (after, diagnostic), before = self.refine(self.observed, [bad, self.monitoring])
                self.assertIn(self.monitoring, [c['text'] for c in after['claims']])
                self.assertEqual(after['claims'], before['claims'])
                self.assertEqual(len(diagnostic['subject_identity_preserved_root_ids']), 2)

    def test_unidentified_or_pronominal_roots_are_preserved(self):
        for extra in ['Тус үйл ажиллагаа нь оролцогчдыг мэдээллээр хангах зорилготой.',
                      'Энэ нэмэлт шаардлага эхийн өөр хэсэгт тайлбарлагдсан.',
                      'Тухайн ажил үнэлгээг дэмжин сайжруулах зорилготой.']:
            with self.subTest(text=extra):
                (after, _), before = self.refine(self.observed, [self.monitoring, extra])
                self.assertEqual(after['claims'], before['claims'])

    def test_opposing_identity_later_in_packed_root_cannot_erase_unknown_prefix(self):
        for separator in [' ', '; ', '\n']:
            packed = 'Үүнийг өдөр тутам хэрэгжүүлэх зорилготой.'+separator+self.evaluation
            with self.subTest(separator=separator):
                (after, _), before = self.refine(self.observed, [self.monitoring, packed])
                self.assertIn('Үүнийг өдөр тутам', '\n'.join(c['text'] for c in after['claims']))

    def test_mixed_subject_root_is_not_discarded_as_an_opposing_definition(self):
        for suffix in ['ийн', 'ийнх', 'той', 'оос', 'т']:
            mixed = self.evaluation+' Мониторинг'+suffix+' холбоотой нэмэлт тайлбар.'
            with self.subTest(suffix=suffix):
                (after, _), before = self.refine(self.observed, [self.monitoring, mixed])
                self.assertEqual(after['claims'], before['claims'])

    def test_requested_subject_dependency_from_opposing_root_is_preserved(self):
        texts = [self.monitoring, self.evaluation,
                 'Мониторингийн оролцогчдод хамаарах эхийн нэмэлт тайлбар.']
        units = evidence_units([dict(source_id=str(i), text=text) for i, text in enumerate(texts)])
        units[1]['context_unit_ids'] = [units[2]['unit_id']]
        roots = [units[0]['unit_id'], units[1]['unit_id']]
        before = resolve_evidence_selection(self.observed, roots, units, max_claims=6)
        self.assertTrue(before['accepted'])
        after, diagnostic = refine_evidence_selection(self.observed, roots, units, before)
        self.assertEqual(after['claims'], before['claims'])
        self.assertIn(units[2]['unit_id'], diagnostic['subject_identity_preserved_context_ids'])

    def test_presentation_suffix_preserves_exact_subject_scope(self):
        query = self.observed+' Нэмэлт тайлбар хэрэггүй.'
        fields = field_evidence_requirements(query)
        self.assertEqual([f['name'] for f in fields], ['monitoring_definition'])
        self.assertTrue(closed_field_selection_query(query, fields))

    def test_unknown_facets_numbers_conditions_and_exclusions_keep_original_selection(self):
        queries = ['Мониторингийн зорилго, давтамж юу вэ?',
                   'Мониторингийн зорилго болон хариуцсан хүний нэрийг хэл.',
                   'Мониторингийн зорилгыг хэл. Хэн хариуцдаг вэ?',
                   '2027 оны мониторингийн зорилго юу вэ?',
                   'Хэрэв шалгалттай бол мониторингийн зорилго юу вэ?',
                   'Зөвхөн мониторингийн зорилгыг хэл; үнэлгээ хэрэггүй.',
                   'Мониторинг биш, үнэлгээний зорилгыг хэл.',
                   'Мониторингийн зорилгыг тайлбарла, харин үнэлгээнийхийг бүү хэл.',
                   'Мониторинг болон үнэлгээний зорилго, давтамжийг харьцуул.']
        for query in queries:
            with self.subTest(query=query):
                self.assertFalse(closed_field_selection_query(query, field_evidence_requirements(query)))
                (after, diagnostic), before = self.refine(query, [self.monitoring, self.evaluation])
                self.assertEqual(after['claims'], before['claims'])
                self.assertFalse(diagnostic['eligible'])

    def test_conditions_or_negation_in_selected_evidence_are_never_pruned(self):
        for extra in ['Хэрэв нөхцөл биелбэл тухайн тайлбар хамаарна.',
                      'Бусад тохиолдолд энэ тайлбар хамаарахгүй.']:
            with self.subTest(extra=extra):
                (after, diagnostic), before = self.refine(self.observed, [self.monitoring, extra])
                self.assertEqual(after['claims'], before['claims'])
                self.assertEqual(diagnostic['reason'], 'condition_or_exception_preserved')


if __name__ == '__main__':
    unittest.main()
