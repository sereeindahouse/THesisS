"""Constructed role/context/conflict controls, not school facts or human gold."""
import unittest

from evidence_contract import exact_field_units, resolve_evidence_selection
from source_fields import structured_field_extract

QUERIES = {
    'rooms': 'Hub center-д багийн ажил хийх өрөө, сэтгэл зүйчийн өрөө байдаг уу?',
    'internship': 'Японд дадлага хийхийн тулд хэн хүсэлт гаргаж, ямар ярилцлага өгдөг вэ?',
    'language': 'Япон коосэнд дэвшин суралцахад япон хэлний ямар түвшин хэрэгтэй вэ?',
    'absence': 'Оюутны зөвлөлийн гишүүн шалтгаангүй хэд тасалбал ямар арга хэмжээтэй вэ?',
}
TEXTS = {
    'rooms': 'Hub Center\nСургуулийн есдүгээр давхарт байрлах суралцах орчин.\n'
        '01\nБагаар ажиллах өрөө\n02\nУншлагын танхим\n03\nСэтгэл зүйчийн өрөө\n'
        'ДАРААГИЙН ХЭСЭГ\nЛекцийн дөрвөн танхим',
    'internship': 'Дадлага хөтөлбөрт хэн хамрагдах вэ?\n'
        'Ахлах курсийн оюутнууд албаар дамжуулан хүсэлтээ гарган, япон хэл дээр ярилцлага өгч, '
        'тэнцсэн тохиолдолд компаниудад дадлага хийх боломжтой. Амралтаар хамрагдана.\n'
        'АЖИЛД ОРОХ АЛХМУУД\nШинэ хөдөлмөрийн гэрээ',
    'language': 'Япон коосэнд дэвшин суралцахад тавигдах шаардлагууд\n'
        '01 Сайн дүнтэй\n02 Япон хэлний N4 түвшний мэдлэг, чадвартай\n'
        '03 Англи хэлний ахисан мэдлэгтэй\nБЭЛТГЭЛ ХӨТӨЛБӨР\nӨөр мэдээлэл',
    'absence': 'Оюутны зөвлөлийн тухай\nГишүүдийн төлөөллийн тухай.\n'
        'Цаг баримтлалт\n9 удаа хоцорвол сануулга. 7 удаа шалтгаангүй тасалвал '
        'эрх түтгэлзүүлэх асуудлыг хэлэлцэнэ.\n⚖️\nЁс зүйн хариуцлага\nӨөр арга хэмжээ.',
}


def source(text, sid='web-fixture', url='https://nmct.edu.mn/example', start=0):
    return dict(source_id=sid, url=url, version=1, text=text, text_scope='main_element',
                start_offset=start, end_offset=start+len(text))


class StructuredFieldTests(unittest.TestCase):
    def extract(self, kind, text=None):
        return structured_field_extract(QUERIES[kind], [source(text or TEXTS[kind])])

    def test_all_four_roles_return_exact_context_bound_physical_spans(self):
        for kind in TEXTS:
            with self.subTest(kind=kind):
                plan=self.extract(kind)
                self.assertIsNotNone(plan)
                units=exact_field_units(plan['parts'])
                result=resolve_evidence_selection(QUERIES[kind], [units[-1]['unit_id']],
                    units, max_characters=1800, max_claims=6)
                self.assertTrue(result['accepted'],result)
                self.assertEqual(len(result['selected_unit_ids']),len(units))
                for unit in units:
                    self.assertEqual(unit['text'],unit['quote'][unit['start']:unit['end']])
                self.assertEqual(units[-1]['context_unit_ids'],[u['unit_id'] for u in units[:-1]])

    def test_room_answer_keeps_requested_rooms_without_another_facility(self):
        plan=self.extract('rooms')
        text='\n'.join(p['source']['text'][p['start']:p['end']] for p in plan['parts'])
        self.assertIn('Hub Center',text)
        self.assertIn('Багаар ажиллах өрөө',text)
        self.assertIn('Сэтгэл зүйчийн өрөө',text)
        self.assertNotIn('Лекц',text)

    def test_internship_keeps_eligibility_channel_interview_and_condition(self):
        plan=self.extract('internship')
        text='\n'.join(p['source']['text'][p['start']:p['end']] for p in plan['parts'])
        for phrase in ('Ахлах курсийн','хүсэлтээ гарган','япон хэл дээр','тэнцсэн тохиолдолд','Амралтаар'):
            self.assertIn(phrase,text)
        self.assertNotIn('хөдөлмөрийн гэрээ',text)

    def test_language_and_absence_copy_dynamic_values_without_answer_constants(self):
        for kind, value in (('language','N4'),('absence','7 удаа')):
            plan=self.extract(kind)
            text='\n'.join(p['source']['text'][p['start']:p['end']] for p in plan['parts'])
            self.assertIn(value,text)
            self.assertNotIn('N2',text)
        plan=self.extract('language')
        selected='\n'.join(p['source']['text'][p['start']:p['end']] for p in plan['parts'])
        self.assertNotIn('03 Англи',selected)

    def test_unknown_added_facets_years_conditions_and_negation_retain_normal_path(self):
        for kind,q in QUERIES.items():
            for query in (q+' Бас төлбөр хэд вэ?', '2027 онд '+q,
                          q.rstrip('?')+', хэрэв тэтгэлэгтэй бол?',
                          'Энэ худал уу? '+q, q.rstrip('?')+' эсвэл өөр шаардлага бий юу?'):
                with self.subTest(kind=kind,query=query):
                    self.assertIsNone(structured_field_extract(query,[source(TEXTS[kind])]))

    def test_dated_or_conditional_prefix_cannot_disappear(self):
        for prefix in ('2023 оны журам.\n','Хэрэв зөвшөөрөлтэй бол\n','Зөвхөн тодорхой хүмүүст\n'):
            for kind in TEXTS:
                with self.subTest(prefix=prefix,kind=kind):
                    self.assertIsNone(self.extract(kind,prefix+TEXTS[kind]))

    def test_numbered_lists_must_be_complete_unique_and_closed(self):
        for kind in ('rooms','language'):
            text=TEXTS[kind]
            close='ДАРААГИЙН ХЭСЭГ' if kind=='rooms' else 'БЭЛТГЭЛ ХӨТӨЛБӨР'
            self.assertIsNone(self.extract(kind,text.split(close)[0].rstrip()))
            self.assertIsNone(self.extract(kind,text.replace('02','04',1)))
            self.assertIsNone(self.extract(kind,text.replace(close,'НЭМЭЛТ НӨХЦӨЛ')))

    def test_other_pathway_or_council_cannot_supply_requested_rule(self):
        self.assertIsNone(self.extract('language',TEXTS['language'].replace('Япон коосэнд','Өөр сургуульд')))
        self.assertIsNone(self.extract('absence',TEXTS['absence'].replace('Оюутны зөвлөл','Багшийн зөвлөл')))

    def test_following_qualification_cannot_be_hidden_by_a_short_heading(self):
        self.assertIsNone(self.extract('internship',TEXTS['internship'].replace('АЖИЛД ОРОХ АЛХМУУД','НЭМЭЛТ НӨХЦӨЛ')))
        self.assertIsNone(self.extract('absence',TEXTS['absence'].replace('Ёс зүйн хариуцлага','Гэхдээ энэ журам үйлчлэхгүй')))

    def test_conflicting_positive_sources_fail_closed(self):
        a=source(TEXTS['language'])
        b=source(TEXTS['language'].replace('N4','N3'),'web-other','https://nmct.edu.mn/other')
        self.assertIsNone(structured_field_extract(QUERIES['language'],[a,b]))

    def test_negative_scoped_source_is_not_ignored_for_a_convenient_positive(self):
        a=source(TEXTS['language'])
        b=source('Хуучин шаардлага\n'+TEXTS['language'],'web-other','https://nmct.edu.mn/other')
        self.assertIsNone(structured_field_extract(QUERIES['language'],[a,b]))

    def test_overlapping_windows_map_back_to_original_sources_without_filling_gaps(self):
        text=TEXTS['rooms'];cut=text.index('02\n')
        a=source(text[:text.index('03\n')],'web-left')
        b=source(text[cut:],'web-right',start=cut)
        plan=structured_field_extract(QUERIES['rooms'],[a,b])
        self.assertIsNotNone(plan)
        for p in plan['parts']:
            self.assertIn(p['source']['source_id'],('web-left','web-right'))
            self.assertEqual(p['source']['text'][p['start']:p['end']],
                text[p['source']['start_offset']+p['start']:p['source']['start_offset']+p['end']])
        b['start_offset']+=1;b['end_offset']+=1
        self.assertIsNone(structured_field_extract(QUERIES['rooms'],[a,b]))

    def test_inconsistent_overlap_never_builds_a_field_plan(self):
        a=source(TEXTS['language'])
        b=source(TEXTS['language'].replace('N4','N3'),'web-other')
        self.assertIsNone(structured_field_extract(QUERIES['language'],[a,b]))

    def test_exact_unit_constructor_rejects_partial_lines_and_invalid_offsets(self):
        s=source('heading\nbody\nend')
        for a,b in ((1,7),(0,3),(-1,7),(0,999)):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):
                exact_field_units([dict(source=s,start=a,end=b)])


if __name__=='__main__':unittest.main()
