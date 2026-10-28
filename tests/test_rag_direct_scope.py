"""Constructed direct-lookup controls; values are not school facts."""
import copy
from pathlib import Path
import unittest

from rag_runtime import ChatRAG, focused_extract, source_extract
from source_fields import field_evidence_requirements, missing_field_evidence, staff_query_scope
from test_rag_runtime import SOURCE, Policy, Retriever, Generator


def interview(extra='', mode=''):
    text = (f'{mode}Ярилцлагын шалгалтаар өөрийгөө илэрхийлэх чадварыг шалгана.\n'
            f'{mode}Ярилцлагын шалгалтад эцэг эх эсвэл асран хамгаалагчтай хамт орно.\n'
            f'{mode}Ярилцлагын шалгалт 27 минут үргэлжилнэ.\n'
            f'{mode}Ярилцлагын шалгалтыг нийт 37 оноогоор дүгнэнэ.' + extra)
    return dict(copy.deepcopy(SOURCE), source_id='constructed-interview', text=text,
                excerpt=text, title='Элсэлтийн шалгалтын журам',
                url='https://nmct.edu.mn/elseltiin-juram/constructed.png',
                text_scope='document_visual_excerpt', page_header='Элсэлтийн журам')


def programme(title='Компьютерын ухааны хөтөлбөр', name='computer-science-program'):
    text = title + '\nПрограммчлалын хэл: Rust, Julia ашиглан төсөл боловсруулна.'
    return dict(copy.deepcopy(SOURCE), source_id='constructed-'+name, text=text,
                excerpt=text, title=title, text_scope='main_element',
                url='https://nmct.edu.mn/programs/'+name)


class NoGeneration(Generator):
    def generate(self, query, sources):
        self.calls += 1
        raise AssertionError('An unsupported direct facet must not fall through to full C.')


def route(query, sources):
    retriever = Retriever()
    retriever.sources = sources
    generator = NoGeneration()
    result = ChatRAG(Path(__file__).resolve().parents[1], Policy(), retriever, generator).route(None, query)
    return result, generator


class DirectLookupScopeTests(unittest.TestCase):
    def unsupported(self, query, sources):
        self.assertIsNone(source_extract(query, sources))
        result, generator = route(query, sources)
        self.assertEqual(result['route'], 'E', result)
        self.assertIsNone(result['answer'])
        if result['reason_code']!='requested_year_not_supported':
            self.assertTrue(result.get('missing_fields'), result)
        self.assertEqual(generator.calls, 0)

    def test_interview_supported_duration_uses_other_values(self):
        source = interview()
        result = source_extract('Ярилцлага хэдэн минут үргэлжилдэг вэ?', [source])
        self.assertIsNotNone(result)
        self.assertIn('27 минут', result[1])
        self.assertNotIn('15 минут', result[1])

    def test_interview_supported_compound_fields_stay_complete(self):
        source = interview()
        queries = (
            'Ярилцлага хэдэн минут үргэлжилж, нийт хэдэн оноотой вэ?',
            'Ярилцлагад хэнтэй хамт орж, хэдэн минут үргэлжлэх вэ?',
            'Ярилцлагаар ямар чадварыг шалгадаг, хэдэн оноогоор дүгнэдэг вэ?',
        )
        for query in queries:
            with self.subTest(query=query):
                result, generator = route(query, [source])
                self.assertEqual(result['route'], 'A', result)
                self.assertIn('27 минут', result['answer'])
                self.assertIn('37 оноо', result['answer'])
                self.assertEqual(generator.calls, 0)

    def test_interview_extra_fee_cannot_become_full_duration_answer(self):
        self.unsupported('Ярилцлага хэдэн минут үргэлжилдэг, хэдэн төгрөгийн төлбөртэй вэ?', [interview()])

    def test_interview_registration_fee_is_not_interview_fee(self):
        for extra in ('\nЭлсэлтийн бүртгэлийн хураамж 12000 төгрөг.',
                      '\nЯрилцлагад орохын өмнө бүртгэлийн хураамж 12000 төгрөг төлнө.'):
            with self.subTest(extra=extra):
                self.unsupported('Ярилцлага хэдэн минут, ярилцлагын төлбөр хэдэн төгрөг вэ?', [interview(extra)])

    def test_explicit_interview_fee_and_mode_can_be_supported(self):
        source = interview('\nОнлайн ярилцлагын шалгалтын хураамж 7300 төгрөг.', mode='Онлайн ')
        result, generator = route('Онлайн ярилцлага хэдэн минут, ярилцлагын хураамж хэдэн төгрөг вэ?', [source])
        self.assertEqual(result['route'], 'A', result)
        self.assertIn('27 минут', result['answer'])
        self.assertIn('7300 төгрөг', result['answer'])
        self.assertEqual(generator.calls, 0)

    def test_interview_mode_is_bound_to_duration_not_online_registration(self):
        query = 'Ярилцлагын шалгалт онлайн бол хэдэн минут үргэлжлэх вэ?'
        for source in (interview(), interview('\nБүртгэлийг онлайнаар хийнэ.')):
            with self.subTest(text=source['text']):
                self.unsupported(query, [source])

    def test_interview_unknown_scope_negation_and_group_do_not_disappear(self):
        for query in (
            'Хэрэв би шалгалтад тэнцвэл ярилцлага хэдэн минут үргэлжлэх вэ?',
            'Гадаад сурагчийн ярилцлага хэдэн минут үргэлжилдэг вэ?',
            'Ярилцлага биш, бусад шалгалт хэдэн минут үргэлжилдэг вэ?',
            'Ярилцлага хэдэн минут үргэлжилж, ямар өрөөнд болох вэ?',
            'Зөвхөн хоёрдугаар курсын ярилцлага хэдэн минут вэ?',
            'Ярилцлага 28 минут үргэлжлэх үү?',
            '2039 оны ярилцлага хэдэн минут үргэлжилдэг вэ?',
        ):
            with self.subTest(query=query):
                self.unsupported(query, [interview()])

    def test_job_interview_does_not_use_admission_duration(self):
        self.assertIsNone(source_extract('Ажлын ярилцлага хэдэн минут үргэлжилдэг вэ?', [interview()]))

    def test_language_examples_are_not_hardcoded(self):
        source = programme()
        result = source_extract('Компьютерын ухааны хөтөлбөрт ямар программчлалын хэл үздэг вэ?', [source])
        self.assertIsNotNone(result)
        self.assertIn('Rust, Julia', result[1])
        self.assertNotIn('Python', result[1])

    def test_another_named_programme_can_supply_its_own_language_examples(self):
        source = programme('Роботик инженерийн хөтөлбөр', 'constructed-robotics')
        result, generator = route('Роботик инженерийн хөтөлбөрт ямар программчлалын хэл үзэх вэ?', [programme(),source])
        self.assertEqual(result['route'], 'A', result)
        self.assertEqual(result['citations'][0]['document_id'], source['source_id'])
        self.assertIn('Rust, Julia', result['answer'])
        self.assertEqual(generator.calls, 0)

    def test_language_wrong_owner_comparison_and_extra_fields_do_not_disappear(self):
        for query in (
            'Химийн инженерийн хөтөлбөрт ямар программчлалын хэл үздэг вэ?',
            'Компьютерын ухааны болон химийн инженерийн хөтөлбөрт ямар программчлалын хэл үздэг вэ?',
            'Компьютерын ухааны хөтөлбөрт ямар программчлалын хэл, хичээл бүр хэдэн кредит вэ?',
            'Гадаад сурагч компьютерын ухааны хөтөлбөрт ямар программчлалын хэл үзэх вэ?',
            '2039 онд компьютерын ухааны хөтөлбөрт ямар программчлалын хэл үзэх вэ?',
            'Компьютерын ухааны хөтөлбөрт ямар программчлалын хэл үздэггүй вэ?',
        ):
            with self.subTest(query=query):
                self.unsupported(query, [programme()])

    def test_interview_field_screen_requires_own_fee_and_mode(self):
        query = 'Онлайн ярилцлага хэдэн минут, ярилцлагын хураамж хэдэн төгрөг вэ?'
        requirements = field_evidence_requirements(query)
        self.assertGreaterEqual(len(requirements), 3)
        missing = missing_field_evidence(requirements, interview()['text'])
        self.assertIn('interview_fee', missing)
        self.assertIn('interview_mode_online', missing)
        self.assertEqual(missing_field_evidence(requirements,
            interview('\nОнлайн ярилцлагын шалгалтын хураамж 7300 төгрөг.', mode='Онлайн ')['text']), [])

    def test_calendar_and_role_words_before_teacher_are_not_people(self):
        source = dict(programme(), title='Роботик инженерийн тэнхим',
            text='Роботик инженерийн тэнхим нь 8 үндсэн багштай.')
        for year in ('2013','2036'):
            for query in (f'{year} онд багш нарын тоо хэд байсан бэ?',
                          f'{year} оны багш нарын талаар мэдээлэл өгөөч.'):
                with self.subTest(query=query):
                    scope=staff_query_scope(query,[source],catalog=[source])
                    self.assertIsNone(scope and scope.get('person'))

    def test_initialled_name_is_not_removed_as_a_calendar_word(self):
        source=dict(programme(),text='Б.Онд багшийн танилцуулга. Роботик хичээл заадаг.')
        for name in ('Б.Онд','Б.Оюун','Батчулуун'):
            scope=staff_query_scope(name+' багшийн мэдээлэл өгөөч.',[source],catalog=[source])
            self.assertEqual(scope['person'],name)


if __name__ == '__main__':
    unittest.main()
