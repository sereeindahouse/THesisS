"""Source structure fixtures; no school facts or model outcomes."""
import unittest
from evidence_contract import evidence_units,resolve_evidence_selection,missing_query_markers
from source_fields import field_evidence_requirements,missing_field_evidence


class ContactCardStructureTests(unittest.TestCase):
    contact=('Хаяг мэдээлэл\nХаяг\nТуршилтын хот\nИмэйл\ncontact@example.org\nАжлын цаг\n'
             'Бямба: 11:00 - 13:00\nНям: Амарна')
    form='Мэдэгдэл илгээх\nНэр *\nИмэйл *\nУтас\nСэдэв * Сонгоно уу\nМэдэгдэл *\nИлгээх'

    def units(self,text):return evidence_units([dict(source_id='fixture',text=text)])

    def test_contact_and_complete_form_are_independent_exact_units(self):
        text=self.contact+'\n'+self.form
        units=self.units(text)
        self.assertEqual([u['text'] for u in units],[self.contact,self.form])
        self.assertEqual(''.join(text.split()),''.join(''.join(u['text'].split()) for u in units))
        selected=resolve_evidence_selection('Бямба, нямын ажлын цаг ба имэйл?',
            [units[0]['unit_id']],units,max_claims=6)
        self.assertTrue(selected['accepted'])
        self.assertNotIn('Мэдэгдэл илгээх','\n'.join(c['text'] for c in selected['claims']))

    def test_missing_form_markers_do_not_create_a_new_boundary(self):
        for replacement in ('Нэр','Иргэний нэр *'):
            self.assertEqual(len(self.units(self.contact+'\n'+self.form.replace('Нэр *',replacement))),1)

    def test_condition_or_prose_prefix_is_never_detached(self):
        for prefix in ('Зөвхөн бүртгэлтэй тохиолдолд\n','Хэрэв хүсэлт батлагдвал\n',
                       'Холбоо барих цаг нь тухайн улирлын бүртгэлээс хамаарч өөрчлөгдөж болно.\n'):
            units=self.units(prefix+self.contact+'\n'+self.form)
            self.assertTrue(any(self.contact in u['text'] and self.form in u['text'] for u in units))

    def test_inline_empty_counter_pair_is_removed_only_from_prefix(self):
        body='Туршилтын тэнхим нь инженерийн мэдлэг, чадвар эзэмшүүлэх чиглэлээр сургалт явуулдаг.'
        units=self.units('Дэлгэрэнгүй\n0 хөтөлбөр 0 багш\n'+body)
        self.assertEqual(units[0]['text'],body)
        later=self.units(body+'\n0 хөтөлбөр 0 багш\nТус тайлангийн хэмжилтийн үр дүнг хадгалсан.')
        self.assertTrue(any('0 хөтөлбөр 0 багш' in u['text'] for u in later))

    def test_condition_before_placeholder_pair_cannot_be_erased(self):
        condition='Зөвхөн бүртгэл батлагдсан тохиолдолд'
        for counters in ('0 хөтөлбөр 0 багш','0 хөтөлбөр\n0 багш'):
            units=self.units(condition+'\n'+counters+'\nТуршилтын тэнхим сургалт явуулдаг.')
            self.assertTrue(any(condition in u['text'] for u in units))
            for u in units:
                if 'сургалт явуулдаг' in u['text']:self.assertIn(condition,u['text'])

    def test_trailing_qualifier_or_prose_blocks_form_split(self):
        for suffix in ('Эдгээр ажлын цаг зөвхөн хичээлийн улиралд хүчинтэй.',
                       'Мэдэгдэл амжилттай илгээгдсэний дараа цаг өөрчлөгдөнө.'):
            text=self.contact+'\n'+self.form+'\n'+suffix
            units=self.units(text)
            self.assertTrue(any(self.contact in u['text'] and suffix in u['text'] for u in units))

    def test_weekend_email_request_requires_complete_same_contact_card(self):
        query='Бямба гарагт сургууль хэдээс хэд хүртэл ажилладаг, нямд ажиллах уу? Ерөнхий имэйлийг нь давхар өгөөч.'
        fields=field_evidence_requirements(query)
        self.assertEqual([f['name'] for f in fields],['school_weekend_hours_and_email'])
        self.assertEqual(missing_field_evidence(fields,self.contact),[])
        for text in ('Бидэнтэй холбоо барина уу.\nБүртгэл 9 сарын 19 хүртэл.',
                     self.contact.replace('Ням: Амарна',''),
                     self.contact.replace('Имэйл\ncontact@example.org','Имэйл *'),
                     self.contact.replace('11:00 - 13:00','32:00 - 49:00')):
            self.assertIn('school_weekend_hours_and_email',missing_field_evidence(fields,text))
        self.assertIn('school_weekend_hours_and_email',missing_field_evidence(fields,
            [self.contact.split('Ажлын цаг')[0],self.contact.split('Ажлын цаг')[1]]))

    def test_other_owners_and_unknown_extra_facet_are_not_silently_closed(self):
        from source_fields import closed_field_selection_query
        for query in ('Номын сан бямба, нямын ажлын цаг ба имэйл?',
                      'Химийн тэнхим бямба, нямын ажлын цаг ба имэйл?',
                      'Компанийн бямба, нямын ажлын цаг ба имэйл?'):
            self.assertNotIn('school_weekend_hours_and_email',[f['name'] for f in field_evidence_requirements(query)])
        query='Сургуулийн бямба, нямын ажлын цаг, имэйл болон захирлын төрсөн өдөр юу вэ?'
        self.assertFalse(closed_field_selection_query(query,field_evidence_requirements(query)))

    def test_clock_schedule_is_not_a_part_time_staff_request(self):
        available=self.contact+'\nТус тэнхим 2 цагийн багштай.'
        for query in ('Сургуулийн бямба ба ням гарагийн цагийн хуваарь, мэдээлэл авах имэйл хаягийг хэлнэ үү.',
                      'Багшийн цагийн хуваарь ямар вэ?'):
            self.assertNotIn('part_time',missing_query_markers(query,self.contact,available))
        self.assertIn('part_time',missing_query_markers('Үндсэн ба цагийн багшийн тоо хэд вэ?',
            'Тэнхим нь 6 үндсэн багштай.','Тэнхим нь 6 үндсэн, 2 цагийн багштай.'))


if __name__=='__main__':unittest.main()
