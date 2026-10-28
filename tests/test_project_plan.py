"""Public plan parsing and progress declarations, without models or HTTP."""
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import project_plan as plan


def week(identity='W01', interval='2026.10.26–11.01', title='Шинэ эхлэл'):
    return (f'### {identity} · {interval} — {title}\n\n'
            '- **Хийх:** Бодит алдааг шалгах.\n'
            '- **Гарах:** Баталгаатай дүн.\n'
            '- **Тэнцэх:** Ижил оролтоор шалгасан.\n'
            '- **Үүрэг/хамаарал:** Кодын ажил үргэлжилнэ.\n')


class ProjectPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / plan.PLAN_PATH
        self.path.parent.mkdir()

    def write(self, text=None):
        text = '# Дипломын төлөвлөгөө\n\nТовч зорилго.\n\n' + (text if text is not None else week())
        self.path.write_text(text, encoding='utf-8')
        return text

    def parse(self, status=None, today=date(2026, 10, 27)):
        return plan.public_plan(self.root, status=status, today=today)

    def test_actual_plan_has_every_week_and_nonweekly_section(self):
        root = Path(__file__).resolve().parents[1]
        result = plan.public_plan(root, today=date(2026, 10, 27))
        self.assertTrue(result['available'])
        self.assertEqual(len(result['weeks']), 32)
        self.assertEqual((result['start_date'], result['end_date']), ('2026-10-26', '2027-05-31'))
        self.assertEqual(result['calendar_week_id'], 'W01')
        self.assertEqual(result['source_sha256'], hashlib.sha256((root / plan.PLAN_PATH).read_bytes()).hexdigest())
        self.assertTrue(result['weeks'][0]['work'])
        self.assertTrue(result['weeks'][0]['deliverables'])
        self.assertTrue(result['weeks'][0]['acceptance'])
        self.assertTrue(result['weeks'][0]['dependencies'])
        self.assertTrue(result['weeks'][-1]['work'])
        self.assertTrue(result['weeks'][-1]['acceptance'])
        self.assertTrue(any('Аргын эх' in item['title'] for item in result['sections']))

    def test_known_fields_not_duplicated_in_unknown_blocks(self):
        self.write(week() + '\n### Тэмдэглэл\nНэмэлт нөхцөл.\n')
        result = self.parse()['weeks'][0]
        self.assertEqual(result['work'], ['Бодит алдааг шалгах.'])
        self.assertEqual(result['dependencies'], ['Кодын ажил үргэлжилнэ.'])
        self.assertEqual([b['text'] for b in result['blocks']], ['Тэмдэглэл', 'Нэмэлт нөхцөл.'])

    def test_final_single_day_and_unlabelled_work(self):
        self.write(week() + '\n### W02 · 2026.11.02 — Нөөц өдөр\n- Багц хүлээлгэн өгөх.\n- **Дууссан гэж үзэх:** Бодит хувилбар хадгалсан.\n')
        result = self.parse(today=date(2026, 11, 2))
        self.assertTrue(result['available'])
        final = result['weeks'][1]
        self.assertEqual((final['start_date'], final['end_date']), ('2026-11-02', '2026-11-02'))
        self.assertEqual(final['work'], ['Багц хүлээлгэн өгөх.'])
        self.assertEqual(final['acceptance'], ['Бодит хувилбар хадгалсан.'])

    def test_year_wrap_with_explicit_year(self):
        self.write(week(interval='2026.12.28–2027.01.03') + '\n' + week('W02', '2027.01.04', 'Нөөц'))
        result = self.parse(today=date(2027, 1, 1))
        self.assertTrue(result['available'])
        self.assertEqual(result['weeks'][0]['end_date'], '2027-01-03')

    def test_year_wrap_with_month_day_end(self):
        self.write(week(interval='2026.12.28–01.03'))
        self.assertEqual(self.parse()['end_date'], '2027-01-03')

    def test_leap_day_accepted_only_in_real_leap_year(self):
        self.write(week(interval='2028.02.28–03.05'))
        self.assertTrue(self.parse(today=date(2028, 2, 29))['available'])
        self.write(week(interval='2027.02.29–03.06'))
        self.assertFalse(self.parse()['available'])

    def test_dates_gap_or_overlap_fail_closed(self):
        for start in ('2026.11.01', '2026.11.03'):
            with self.subTest(start=start):
                self.write(week() + '\n' + week('W02', start))
                self.assertFalse(self.parse()['available'])

    def test_duplicate_or_nonsequential_week_ids_fail_closed(self):
        for identity in ('W01', 'W03', 'W00'):
            with self.subTest(identity=identity):
                self.write(week() + '\n' + week(identity, '2026.11.02'))
                self.assertFalse(self.parse()['available'])

    def test_malformed_week_heading_not_silently_dropped(self):
        self.write(week() + '\n### W02 · bad-date — Буруу\n')
        self.assertFalse(self.parse()['available'])

    def test_only_last_interval_can_be_short(self):
        self.write(week(interval='2026.10.26') + '\n' + week('W02', '2026.10.27'))
        self.assertFalse(self.parse()['available'])

    def test_interval_longer_than_seven_days_rejected(self):
        self.write(week(interval='2026.10.26–11.02'))
        self.assertFalse(self.parse()['available'])

    def test_calendar_past_does_not_declare_work_done(self):
        self.write(week() + '\n' + week('W02', '2026.11.02'))
        result = self.parse(today=date(2026, 11, 2))
        self.assertEqual(result['weeks'][0]['calendar_state'], 'past')
        self.assertEqual(result['weeks'][0]['status'], 'planned')
        self.assertEqual(result['weeks'][1]['calendar_state'], 'current')
        self.assertEqual(result['current_week_id'], 'W02')

    def test_explicit_active_work_separate_from_calendar_week(self):
        self.write(week() + '\n' + week('W02', '2026.11.02'))
        status = dict(current=dict(week_id='W01', title='Дуусаагүй ажил', done=['Бэлтгэл'], next=['Хэрэгжүүлэх']),
                      weeks=dict(W01=dict(state='in_progress', evidence=['Шалгалтын бүртгэл'])))
        result = self.parse(status=status, today=date(2026, 11, 2))
        self.assertEqual(result['current_week_id'], 'W01')
        self.assertEqual(result['calendar_week_id'], 'W02')
        self.assertEqual(result['current']['done'], ['Бэлтгэл'])
        self.assertEqual(result['weeks'][0]['status'], 'in_progress')

    def test_done_requires_explicit_evidence(self):
        self.write()
        result = self.parse(status=dict(weeks=dict(W01=dict(state='done'))))
        self.assertEqual(result['weeks'][0]['status'], 'partial')
        self.assertEqual(result['weeks'][0]['status_label'], 'Нотолгоо дутуу')
        result = self.parse(status=dict(weeks=dict(W01=dict(state='done', evidence=['Бодит тестийн дүн']))))
        self.assertEqual(result['weeks'][0]['status'], 'done')

    def test_status_only_whitelists_safe_bounded_fields(self):
        self.write()
        status = dict(secret='PRIVATE TOKEN', raw_audio=dict(transcript='PRIVATE TRANSCRIPT'),
            path='C:/private/key.json', current=dict(week_id='W01', title='Өнөөдөр',
                secret='PRIVATE PERSON', done=['Зөв', {'bad': 'PRIVATE'}], next=['x'*5000]*60),
            weeks=dict(W01=dict(state='imagined', evidence=['Тэмдэглэл'], secret='PRIVATE'),
                       W99=dict(state='done', evidence=['PRIVATE'])),
            components=[dict(id='stt',label='STT',state='in_progress',detail='Бодит төлөв',
                             evidence_label='Суурь хэмжилт',secret='PRIVATE'),
                        dict(id='stt',label='Давхардал'),dict(id='../private',label='Буруу')])
        result = self.parse(status=status)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result['current']['done'], ['Зөв'])
        self.assertEqual(len(result['current']['next']), 24)
        self.assertEqual(len(result['current']['next'][0]), 3000)
        self.assertEqual(result['weeks'][0]['status'], 'planned')
        self.assertEqual(len(result['components']), 1)

    def test_malformed_status_types_cannot_crash_or_leak(self):
        self.write()
        for status in (None, [], 'PRIVATE', dict(current=[], weeks=[], components='PRIVATE'),
                       dict(current=dict(week_id=[]),weeks=dict(W01=dict(state=[])),components=[dict(id=[],label={})])):
            with self.subTest(status=status):
                result = self.parse(status=status)
                self.assertTrue(result['available'])
                self.assertNotIn('PRIVATE', json.dumps(result))

    def test_unknown_week_ids_do_not_set_current(self):
        self.write()
        result=self.parse(status=dict(current=dict(week_id='W99')))
        self.assertEqual(result['current_week_id'], 'W01')

    def test_invalid_unicode_status_cannot_break_json_response(self):
        self.write()
        status=dict(current=dict(week_id='W01',title='\ud800',done=['\udfff','Бодит']),
                    components=[dict(id='stt',label='\ud800',detail='PRIVATE')])
        result=self.parse(status=status)
        json.dumps(result,ensure_ascii=False).encode('utf-8')
        self.assertEqual(result['current']['done'],['Бодит'])
        self.assertEqual(result['components'],[])

    def test_missing_and_no_week_plan_return_fixed_safe_message(self):
        missing=self.parse()
        self.assertFalse(missing['available'])
        self.assertNotIn(str(self.root), str(missing))
        self.write('No schedule yet.')
        self.assertFalse(self.parse()['available'])

    def test_oversize_or_invalid_unicode_or_control_character_rejected(self):
        for payload in (b'x'*(plan.MAX_BYTES+1), b'\xffbad', (self.write()+'\x00').encode()):
            with self.subTest(size=len(payload)):
                self.path.write_bytes(payload)
                self.assertFalse(self.parse()['available'])

    def test_path_escape_fails_before_reading_external_file(self):
        self.write()
        outside=self.root.parent/'private-plan.md'
        with patch.object(plan.Path,'resolve',side_effect=[self.root,outside]), \
                patch.object(plan.Path,'open',side_effect=AssertionError('Must not read escaped target')):
            self.assertFalse(self.parse()['available'])

    def test_arbitrary_config_path_never_read(self):
        self.write()
        secret=self.root/'private.json';secret.write_text('PRIVATE SECRET',encoding='utf-8')
        result=self.parse(status=dict(path=str(secret),source_path=str(secret)))
        self.assertTrue(result['available'])
        self.assertEqual(result['source_path'],plan.PLAN_PATH)
        self.assertNotIn('PRIVATE SECRET',json.dumps(result))

    def test_source_hash_is_the_same_single_captured_read(self):
        self.write()
        captured=self.path.read_bytes()
        original_open=Path.open
        calls=[]
        def mutate_after_open(path,*args,**kwargs):
            if path==self.path and args==('rb',):
                calls.append(path)
                self.path.write_bytes(b'Changed after the first captured read.')
                return io.BytesIO(captured)
            return original_open(path,*args,**kwargs)
        with patch.object(plan.Path,'open',new=mutate_after_open):
            result=self.parse()
        self.assertEqual(len(calls),1)
        self.assertEqual(result['source_sha256'],hashlib.sha256(captured).hexdigest())
        self.assertNotEqual(result['source_sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_script_html_and_links_are_inert_strings_not_rendered(self):
        malicious='<script>alert(1)</script> [unsafe](javascript:alert(2))'
        self.write(malicious+'\n\n'+week(title='<img src=x onerror=alert(3)>'))
        result=self.parse()
        self.assertTrue(result['available'])
        self.assertEqual(result['sections'][0]['blocks'][-1]['text'],malicious)
        self.assertEqual(result['weeks'][0]['title'],'<img src=x onerror=alert(3)>')
        self.assertFalse(any('html' in block for section in result['sections'] for block in section['blocks']))

    def test_nonweekly_tables_rules_and_unknown_content_preserved(self):
        text=('# Plan\n\nIntro.\n\n## Policy\n1. First rule\n2. Second rule\n\n'
              '| Head | Value |\n|---|---|\n| RAG | 1 |\n\n'+week()+'\n## Sources\nSource detail.\n')
        self.path.write_text(text,encoding='utf-8')
        result=self.parse()
        section=next(s for s in result['sections'] if s['title']=='Policy')
        self.assertEqual([b['type'] for b in section['blocks']],['list_item','list_item','table_row','table_row'])
        self.assertEqual(section['blocks'][0]['text'],'1. First rule')
        self.assertTrue(any(s['title']=='Sources' and s['blocks'][0]['text']=='Source detail.' for s in result['sections']))

    def test_too_long_headings_or_paragraphs_fail_closed(self):
        self.write(week(title='x'*501))
        self.assertFalse(self.parse()['available'])
        self.write('x'*(plan.MAX_TEXT+1)+'\n\n'+week())
        self.assertFalse(self.parse()['available'])

    def test_current_date_edges_and_outside_plan(self):
        self.write()
        for day in (date(2026,10,26),date(2026,11,1)):
            self.assertEqual(self.parse(today=day)['calendar_week_id'],'W01')
        self.assertIsNone(self.parse(today=date(2026,10,25))['calendar_week_id'])
        self.assertIsNone(self.parse(today=date(2026,11,2))['calendar_week_id'])
        self.assertFalse(self.parse(today='2026-10-27')['available'])

    def three_sections(self, mapping='| W01 | I, II, III |'):
        sections='## Дипломын 3 үндсэн хэсэг\n\n'
        for identity in ('I','II','III'):
            sections+=(f'### {identity} · Үр дүн {identity}\n\n'
                       '- **Үр дүн:** Шалгаж нотлох үр дүн.\n'
                       '- **Дэд ажил:** Нэгдүгээр ажил.\n'
                       '- **Дэд ажил:** Хоёрдугаар ажил.\n'
                       '- **Бэлэн:** Хэрэгжсэн суурь.\n'
                       '- **Үлдсэн:** Хэмжилт.\n'
                       '- **Дуусах шалгуур:** Эхтэй ижил оролтын шалгалт.\n'
                       '- **Нотолгоо:** [Хувийн файл](../private.txt) — автоматаар нээхгүй.\n\n')
        return sections+'## Долоо хоног ба үндсэн хэсгийн холбоо\n\n| Долоо хоног | Хэсэг |\n|---|---|\n'+mapping+'\n\n'

    def test_three_outcomes_and_complete_week_mapping_come_from_plan(self):
        self.write(self.three_sections()+week())
        result=self.parse()
        self.assertTrue(result['available'])
        self.assertEqual([item['id'] for item in result['workstreams']],['I','II','III'])
        self.assertEqual(result['workstreams'][1]['subgoals'],['Нэгдүгээр ажил.','Хоёрдугаар ажил.'])
        self.assertEqual(result['weeks'][0]['workstream_ids'],['I','II','III'])
        self.assertTrue(all(item['week_ids']==['W01'] for item in result['workstreams']))
        self.assertNotIn('status',result['workstreams'][0])
        self.assertNotIn('completion_percentage',result['workstreams'][0])

    def test_legacy_plan_has_no_invented_outcomes_or_week_mapping(self):
        self.write()
        result=self.parse()
        self.assertEqual(result['workstreams'],[])
        self.assertNotIn('workstream_ids',result['weeks'][0])

    def test_partial_or_duplicate_three_outcome_declaration_is_not_presented(self):
        for before,after in [('### III ·','### II ·'),('### III ·','### IV ·'),('**Үр дүн:**','**Непознато:**')]:
            with self.subTest(before=before,after=after):
                self.write(self.three_sections().replace(before,after)+week())
                result=self.parse()
                self.assertTrue(result['available'])
                self.assertEqual(result['workstreams'],[])

    def test_incomplete_or_unknown_week_links_do_not_partially_attach(self):
        for mapping in ('| W01 | I |','| W01 | I, IV |\n| W02 | II |',
                        '| W01 | I |\n| W01 | II |\n| W02 | III |',
                        '| W01 | I, I |\n| W02 | III |',
                        '| W01 | I |\n| W02 | II |\n| W99 | III |'):
            with self.subTest(mapping=mapping):
                self.write(self.three_sections(mapping)+week()+week('W02','2026.11.02–11.08'))
                result=self.parse()
                self.assertEqual(len(result['workstreams']),3)
                self.assertTrue(all(not item['week_ids'] for item in result['workstreams']))
                self.assertTrue(all('workstream_ids' not in item for item in result['weeks']))

    def test_complete_mixed_mapping_is_not_exclusive_or_calendar_based(self):
        self.write(self.three_sections('| W01 | I, II |\n| W02 | II, III |')+week()+week('W02','2026.11.02–11.08'))
        result=self.parse(today=date(2027,5,31))
        self.assertEqual(result['workstreams'][1]['week_ids'],['W01','W02'])
        self.assertEqual(result['workstreams'][2]['week_ids'],['W02'])
        self.assertTrue(all(item['status']=='planned' for item in result['weeks']))


if __name__=='__main__':
    unittest.main()
