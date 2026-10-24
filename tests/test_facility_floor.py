"""Facility/floor relation tests with constructed values, not school accuracy."""
import unittest
from source_fields import (facility_floor_requirements,facility_floor_records,requested_detail,
    detail_supported,field_evidence_requirements,missing_field_evidence,field_extract)


def source(text):
    return dict(source_id='example',text=text,title='Сургалтын орчин',
        url='https://nmct.edu.mn/about/environment')


class FacilityFloorTests(unittest.TestCase):
    query='Номын сан хэдэн давхарт байдаг вэ?'

    def supported(self,text,q=None):
        return detail_supported('facility_floor',text,q or self.query)

    def test_exact_library_heading_owns_its_floor_sentence(self):
        text='Дэд бүтэц\nНомын сан, спорт, хоол\nНомын сан\nOpenShelf програм\n7 давхрын 123.45 м² талбай бүхий орчин. Программыг 2003 оноос ашиглана.\n900+\nном'
        row=source(text)
        result=field_extract(self.query,[row])
        self.assertEqual(result,(row,'Номын сан\nOpenShelf програм\n7 давхрын 123.45 м² талбай бүхий орчин.'))
        self.assertTrue(self.supported(result[1]))
        req=field_evidence_requirements(self.query)
        self.assertEqual([r['name'] for r in req],['facility_floor_library'])
        self.assertEqual(missing_field_evidence(req,result[1]),[])
        self.assertEqual(requested_detail(self.query),'facility_floor')

    def test_own_inline_location_is_not_hardcoded_to_a_floor_or_building(self):
        for text in ['Номын сан 4-р давхарт байрладаг.',
                     'Сургуулийн номын сан гуравдугаар давхарт байрладаг.',
                     'Номын сан\n22 давхарт байрлах өрөө.']:
            self.assertTrue(self.supported(text),text)

    def test_numbered_room_list_and_floor_area_do_not_answer_location(self):
        for text in ['593 м² талбай\n01\nНомын сан\n02\nНомын фонд\n10\nАриун цэврийн өрөө',
                     '01 Номын сан\n10 Ариун цэврийн өрөө',
                     'Номын сан\n400 м² талбай\n7 өрөө',
                     '10\nНомын сан',
                     'Номын сан 2 давхар барилгад байрладаг.']:
            self.assertFalse(self.supported(text),text)
            self.assertIsNone(field_extract(self.query,[source(text)]))

    def test_other_facility_or_building_floor_is_not_borrowed(self):
        for text in ['Хоолны газар 7-р давхарт байрладаг. Номын сангийн мэдээлэл удахгүй нэмэгдэнэ.',
                     'Номын сан\nХоолны газар\n7 давхарт байрлах орчин.',
                     'А байр\n7 давхарт байрлах сургалтын төв.\nБ байр\n01\nНомын сан\n02\nХурлын өрөө',
                     'Номын сан хоолны газрын 7 давхарт байрладаг.']:
            self.assertFalse(self.supported(text),text)
        self.assertFalse(self.supported('Номын сан\n7 давхарт байрлах орчин.','Б байрны номын сан хэдэн давхарт байдаг вэ?'))

    def test_nearest_target_heading_blocks_another_facility(self):
        text='Номын сан\nХоолны газрын тайлбар\n7 давхрын орчин.'
        self.assertFalse(self.supported(text))
        text='Биеийн тамирын заал\n7 давхрын орчин.\nНомын сан\nOpenShelf програм\nТайлбар удахгүй нэмэгдэнэ.'
        self.assertFalse(self.supported(text))
        self.assertFalse(self.supported('Номын сан\nБ байр\n7 давхрын орчин.'))

    def test_container_membership_requires_complete_explicit_relation(self):
        text='Learning Commons\nСургуулийн 6 давхарт байрлах төвийн бүрэлдэхүүнд:\n01\nНомын сан\n02\nХурлын өрөө'
        self.assertTrue(self.supported(text))
        result=field_extract(self.query,[source(text)])
        self.assertEqual(result[1],'Learning Commons\nСургуулийн 6 давхарт байрлах төвийн бүрэлдэхүүнд:\n01\nНомын сан')
        for altered in [text.replace('төвийн бүрэлдэхүүнд','төв'),
                        text.replace('Номын сан','Номын фонд'),
                        text.replace('6 давхарт','600 м² талбайд')]:
            self.assertFalse(self.supported(altered),altered)

    def test_unknown_conditions_are_not_dropped(self):
        for text in ['Номын сан 7-р давхарт байрладаг гэсэн мэдээлэл батлагдаагүй.',
                     'Номын сан\n7 давхрын орчин. Хэрэв гэрээ батлагдвал ашиглана.',
                     'Номын сан 7-р давхарт байрлах болно гэж төлөвлөсөн.',
                     'Номын сан 7-р давхарт байрладаггүй.']:
            self.assertFalse(self.supported(text),text)
        self.assertFalse(self.supported('Номын сан 7-р давхарт байрладаг.',
            'Хэрэв өөр байр руу нүүсэн бол номын сан хэдэн давхарт байдаг вэ?'))

    def test_named_other_facility_has_its_own_floor_contract(self):
        q='Хоолны газар хэдэн давхарт байдаг вэ?'
        self.assertTrue(facility_floor_requirements(q))
        self.assertFalse(self.supported('Номын сан 7-р давхарт байрладаг.',q))
        self.assertTrue(self.supported('Хоолны газар 4-р давхарт байрладаг.',q))

    def test_direct_lookup_does_not_omit_an_extra_requested_facet(self):
        row=source('Номын сан\n7 давхрын 123 м² талбай бүхий орчин.')
        for q in ['Номын сан хэдэн давхарт байдаг вэ, хэзээ хаадаг вэ?',
                  'Номын сан хэдэн давхарт байдаг, номын санчийн нэр хэн бэ?',
                  'Номын сан болон хоолны газар хэдэн давхарт байдаг вэ?']:
            self.assertIsNone(field_extract(q,[row]),q)


if __name__=='__main__':unittest.main()
