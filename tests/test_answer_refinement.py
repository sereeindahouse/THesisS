"""Constructed conservative rendering regressions; no school facts or inference."""
from copy import deepcopy
import unittest
from evidence_contract import evidence_units, resolve_evidence_selection
from rag_runtime import refine_evidence_selection
from source_fields import closed_field_selection_query, field_evidence_requirements


def html(text, sid='one', offset=0, **extra):
    return dict(source_id=sid, text=text, url='https://nmct.edu.mn/fixture',version=1,
                text_scope='main_element',start_offset=offset,end_offset=offset+len(text),**extra)


class ExactOverlapTests(unittest.TestCase):
    heading='Номын сангийн тухай\n'
    body='Номын сан 2043 онд шинэ үйлчилгээг эхлүүлсэн.'

    def pair(self):
        return [html(self.heading+self.body),html(self.body,'two',len(self.heading))]

    def resolve(self,sources):
        units=evidence_units(sources)
        result=resolve_evidence_selection('',[u['unit_id'] for u in units],units,max_claims=6)
        self.assertTrue(result['accepted'],result)
        return result,units

    def test_same_physical_capture_containment_is_rendered_once(self):
        result,units=self.resolve(self.pair())
        self.assertEqual(len(result['claims']),1)
        self.assertEqual(result['claims'][0]['text'],self.heading+self.body)
        self.assertEqual(result['duplicate_unit_coverage'],{units[1]['unit_id']:units[0]['unit_id']})
        self.assertEqual(len(result['expanded_unit_ids']),2)

    def test_different_page_version_or_position_is_never_string_deduplicated(self):
        for change in [dict(url='https://nmct.edu.mn/another'),dict(version=2),dict(start_offset=900,end_offset=900+len(self.body))]:
            sources=self.pair();sources[1].update(change)
            with self.subTest(change=change):self.assertEqual(len(self.resolve(sources)[0]['claims']),2)

    def test_unknown_coordinate_or_non_html_scope_does_not_collapse(self):
        for change in [dict(text_scope='document_visual_excerpt'),dict(text_scope='client_tab_field_excerpt'),dict(start_offset=None)]:
            sources=self.pair();sources[1].update(change)
            with self.subTest(change=change):self.assertEqual(len(self.resolve(sources)[0]['claims']),2)

    def test_same_page_repeated_words_at_different_offsets_remain_distinct(self):
        sources=[html(self.body),html(self.body,'two',len(self.body)+1)]
        self.assertEqual(len(self.resolve(sources)[0]['claims']),2)

    def test_tampered_duplicate_is_rejected_before_redundancy_filter(self):
        units=evidence_units(self.pair());units[1]['text']=self.body.replace('2043','2044')
        result=resolve_evidence_selection('',[u['unit_id'] for u in units],units,max_claims=6)
        self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'invalid_evidence_unit')

    def test_larger_whole_span_preserves_scope_and_exception(self):
        whole='Нөхцөл\n'+self.body+' Харин ням гарагт энэ үйлчилгээ ажиллахгүй.'
        sources=[html(whole),html(self.body,'two',len('Нөхцөл\n'))]
        result,_=self.resolve(sources)
        self.assertEqual(result['claims'][0]['text'],whole)
        self.assertIn('ажиллахгүй',result['claims'][0]['text'])

    def test_identical_intervals_keep_first_with_stable_citation_source(self):
        sources=[html(self.body),html(self.body,'two')]
        result,_=self.resolve(sources)
        self.assertEqual(len(result['claims']),1)
        self.assertEqual(result['claims'][0]['source_id'],'one')


class ClosedSelectionTests(unittest.TestCase):
    year='Сургууль байгуулагдсан оныг хэл.'
    history='Туршилтын коллеж 2043 онд байгуулагдсан.'
    other='2048\nТөгсөгчдийн өдөр\nАнхны төгсөгчид уулзалт хийв.'

    def refine(self,query,texts):
        units=evidence_units([html(text,str(i)) for i,text in enumerate(texts)])
        roots=[u['unit_id'] for u in units]
        result=resolve_evidence_selection(query,roots,units,max_claims=6)
        self.assertTrue(result['accepted'],result)
        return refine_evidence_selection(query,roots,units,result),result

    def eligible(self,query):
        return closed_field_selection_query(query,field_evidence_requirements(query))

    def test_complete_founding_year_removes_unasked_graduation_root(self):
        (after,diag),before=self.refine(self.year,[self.history,self.other])
        self.assertEqual(len(after['claims']),1)
        self.assertEqual(after['claims'][0]['text'],self.history)
        self.assertEqual(diag['reason'],'closed_fields_complete_subset')
        self.assertLess(diag['after_characters'],diag['before_characters'])

    def test_founder_location_and_other_unknown_extra_facets_disable_pruning(self):
        for extra in ['үүсгэн байгуулагч нь хэн бэ','тухайн үеийн захирал хэн бэ','хаана байгуулагдсан бэ']:
            query='Сургууль хэдэн онд байгуулагдсан, '+extra+'?'
            with self.subTest(extra=extra):
                self.assertFalse(self.eligible(query))
                (after,diag),before=self.refine(query,[self.history,'Үүсгэн байгуулагч нь туршилтын төлөөлөгч хүн юм.'])
                self.assertEqual(after['claims'],before['claims']);self.assertFalse(diag['eligible'])

    def test_unknown_prefix_sentence_or_explicit_year_is_not_a_closed_question(self):
        for query in ['Хаана байрладаг вэ? '+self.year,'Номын сан ба '+self.year,
                      'Байгуулагчийг нэрлээд сургууль байгуулагдсан оныг хэл.',
                      '2021 онд шинэчлэгдсэн сургууль байгуулагдсан оныг хэл.',
                      self.year+' Байгуулагч нь хэн бэ?']:
            with self.subTest(query=query):self.assertFalse(self.eligible(query))

    def test_direction_name_only_grammar_keeps_complete_pair(self):
        query='Чанарын баталгаажуулалтын хоёр урсгалын чиглэл ба нэрийг тус тус хэлнэ үү.'
        intro='Үйл ажиллагаа нь хоёр чиглэлийн урсгалд суурилсан бүтэцтэй хэрэгжинэ.'
        cards=('Доороос дээш\nСанал нэгтгэх\nАжилтнаас удирдлагад хүрэх оролцоонд суурилсан урсгал.\n'
               'Дээрээс доош\nДэмжлэг үзүүлэх\nУдирдлагаас ажилтанд хүрэх зөвлөгөөний урсгал.')
        (after,diag),before=self.refine(query,[intro+'\n'+cards,'Удирдлагын уулзалт долоо хоног бүр болдог.'])
        self.assertTrue(self.eligible(query));self.assertTrue(diag['eligible'])
        self.assertEqual(len(after['claims']),1)
        self.assertIn('Доороос дээш',after['claims'][0]['text'])
        self.assertIn('Дээрээс доош',after['claims'][0]['text'])

    def test_extra_flow_purpose_year_or_correctness_request_is_not_closed(self):
        for extra in ['зорилгыг','ямар онд бий болсон','аль нь зөв эсэхийг']:
            query='Хоёр урсгалын чиглэл ба нэр, '+extra+' хэлнэ үү.'
            with self.subTest(extra=extra):self.assertFalse(self.eligible(query))

    def test_conditional_or_negative_selected_evidence_is_never_pruned(self):
        for text in ['Хэрэв нөхцөл биелбэл энэ он хамаарна.','Бусад үед энэ мэдээлэл хамаарахгүй.']:
            with self.subTest(text=text):
                (after,diag),before=self.refine(self.year,[self.history,text])
                self.assertEqual(after['claims'],before['claims'])
                self.assertEqual(diag['reason'],'condition_or_exception_preserved')

    def test_nonempty_but_partial_contract_is_not_general_minimization(self):
        query='Сургууль хэдэн онд байгуулагдсан, үүсгэн байгуулагчийн нэрийг хэл.'
        self.assertTrue(field_evidence_requirements(query))
        self.assertFalse(self.eligible(query))

    def test_inflected_student_count_is_not_mistaken_for_a_year_only_query(self):
        query='Сургууль байгуулагдсан оныг, оюутны тоог хэл.'
        self.assertTrue(field_evidence_requirements(query))
        self.assertFalse(self.eligible(query))
        (after,diag),before=self.refine(query,[self.history,'Анхны 71 оюутан дөрвөн бүлэгт хичээллэв.'])
        self.assertEqual(after['claims'],before['claims'])

    def test_query_presentation_and_submitted_text_are_preserved(self):
        query=self.year+' Нэмэлт тайлбар хэрэггүй.';original=query
        self.assertTrue(self.eligible(query));self.assertEqual(query,original)


if __name__=='__main__':unittest.main()
