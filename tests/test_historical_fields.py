"""Constructed positive and role-confusion controls; dates are invented."""
import unittest
from historical_fields import event_requirements,event_supported,event_search_query


class EventFieldsTests(unittest.TestCase):
    def test_first_graduation_needs_own_year_and_count(self):
        req=event_requirements('Сургууль хэзээ байгуулагдаад анхны төгсөгчид хэдэн онд хэдүүлээ төгссөн бэ?')
        self.assertEqual(len(req),2)
        good='2041\nАнхны төгсөлт\nАнхны 17 төгсөгч дипломоо гардан авчээ.'
        for r in req:self.assertTrue(event_supported(r,good))
        wrong='2035\nАнхны 70 оюутан 4 бүлэгтэйгээр хичээллэв.'
        for r in req:self.assertFalse(event_supported(r,wrong))
        for r in req:self.assertFalse(event_supported(r,'2041 онд анхны 17 төгсөгч төгсөхөөр төлөвлөж байна.'))
        for bad in ('2041\nАнхны 17 төгсөгч дипломоо гардан аваагүй.',
                    '2041\nХэрэв анхны 17 төгсөгч дипломоо гардан авбал баяр хүргэнэ.'):
            for r in req:self.assertFalse(event_supported(r,bad))

    def test_neighbouring_event_date_does_not_date_graduation(self):
        r=event_requirements('Анхны төгсөгчид хэдэн онд төгссөн бэ?')[0]
        self.assertFalse(event_supported(r,'2041 онд багш нар шагнал авав. Анхны 17 төгсөгч дипломоо гардан авав.'))
        self.assertFalse(event_supported(r,'Анхны 17 төгсөгч дипломоо гардан авав.\n2045\nШинэ байр нээгдэв.'))

    def test_natural_first_graduate_count_wordings_keep_the_same_event_role(self):
        for q in ('Анх хэдэн хүн төгссөн бэ?','Анхны төгсөгчдийн тоо хэд вэ?'):
            requirements=event_requirements(q)
            self.assertEqual([r['name'] for r in requirements],['first_graduation_count'])
            self.assertTrue(event_supported(requirements[0],'Анхны 17 төгсөгч дипломоо гардан авав.'))
            self.assertFalse(event_supported(requirements[0],'Анхны 70 оюутан 4 бүлэгтэйгээр хичээллэв.'))

    def test_programme_year_is_bound_to_named_programme_and_opening(self):
        q='Компьютерын ухааны хөтөлбөрийг анх хэдэн онд нээсэн бэ?'
        req=event_requirements(q)
        self.assertEqual(len(req),1)
        r=req[0]
        self.assertTrue(event_supported(r,'2042\nШинэ хөтөлбөр\nКомпьютерийн ухааны хөтөлбөр шинээр нээгдэж, анхны элсэгчдээ хүлээн авав.'))
        self.assertTrue(event_supported(r,'Компьютерийн ухааны хөтөлбөрийг 2042 онд нээсэн.'))
        self.assertTrue(event_supported(r,'2042 онд Компьютерийн ухааны хөтөлбөр нээгдэв.'))
        for bad in ('Компьютерийн ухааны хөтөлбөр инженер бэлтгэнэ.',
                    '2042\nХимийн хөтөлбөр шинээр нээгдэв.',
                    '2042\nКомпьютерийн ухааны хөтөлбөр нээгдээгүй.',
                    '2042\nКомпьютерийн ухааны тэнхим тайлбарлав: Химийн хөтөлбөр шинээр нээгдэв.',
                    '2042\nКомпьютерийн ухааны хөтөлбөрийг нээсэн гэх мэдээлэл батлагдаагүй.',
                    '2042 онд сургуулийн байр нээгдэв. Компьютерийн ухааны хөтөлбөр шинээр нээгдэв.'):
            self.assertFalse(event_supported(r,bad),bad)
        self.assertIn('нээгдсэн',event_search_query(q))
        self.assertNotIn('2022',event_search_query(q))

    def test_ordinary_programme_and_founding_queries_unchanged(self):
        for q in ('Ямар хөтөлбөртэй вэ?','Сургууль хэдэн онд байгуулагдсан бэ?','Програмчлалын хэл заадаг уу?'):
            self.assertEqual(event_requirements(q),[])
            self.assertIsNone(event_search_query(q))

    def test_first_programme_intake_has_its_own_event_not_school_intake(self):
        q='Компьютерын ухааны хөтөлбөр анхны элсэгчдээ хэдэн онд авсан бэ?'
        req=event_requirements(q)
        self.assertEqual(len(req),1)
        self.assertEqual(req[0]['event'],'programme_first_intake')
        self.assertTrue(event_supported(req[0],
            '2042\nКомпьютерийн ухааны хөтөлбөр шинээр нээгдэж, анхны элсэгчдээ хүлээн авав.'))
        for bad in ('2042\nХимийн хөтөлбөр анхны элсэгчдээ хүлээн авав.',
                    '2042\nТуршилтын сургууль анхны 70 оюутнаа хүлээн авав.',
                    '2042\nКомпьютерийн ухааны хөтөлбөр анхны элсэгчдээ хүлээн аваагүй.'):
            self.assertFalse(event_supported(req[0],bad))
        self.assertTrue(event_requirements('Компьютерын ухааны хөтөлбөрийг 2042 онд нээсэн үү?'))
