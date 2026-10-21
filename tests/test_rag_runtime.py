import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rag_runtime import ChatRAG, GroundedGenerator, source_extract, focused_extract, article_evidence_sources, dated_news_evidence_sources
from evidence_contract import evidence_units

SOURCE = dict(source_id='web-test', text='Сургалтын төлбөр: жилд 8,280,000 ₮.',
              excerpt='Сургалтын төлбөр: жилд 8,280,000 ₮.', url='https://nmct.edu.mn/elselt',
              title='Элсэлт 2026', chunk_id=1, version=1, retrieved_at='2026-10-10',
              source_updated_at=None, lexical_overlap_count=1)
CLAIM = dict(text='Сургалтын төлбөр жилд 8,280,000 ₮.', source_id='web-test',
             quote=SOURCE['text'])


class ArticleScopeTests(unittest.TestCase):
    def test_requested_news_month_excludes_another_event_stage_published_later(self):
        first=dict(SOURCE,url='https://nmct.edu.mn/news/a',text='Бүх мэдээ\n2029 оны хоёрдугаар сарын 7 15 үзсэн\nШалгарах эрх авлаа.')
        later=dict(SOURCE,url='https://nmct.edu.mn/news/b',text='Бүх мэдээ\n2029 оны тавдугаар сарын 3 25 үзсэн\nЭцсийн медаль хүртлээ.')
        continuation=dict(first,source_id='web-continuation',text='Дараагийн хэсэг.')
        self.assertEqual(dated_news_evidence_sources('2029 оны хоёрдугаар сарын мэдээнд хэрхэн эрх авсан бэ?',
                         [first,later,continuation]),[first,continuation])

    def test_event_date_inside_prose_is_not_publication_date(self):
        one=dict(SOURCE,text='2029 оны хоёрдугаар сарын 7-нд уулзалт болсон.')
        values=[one]
        self.assertEqual(dated_news_evidence_sources('2029 оны хоёрдугаар сарын мэдээнд?',values),values)
        self.assertEqual(dated_news_evidence_sources('Уулзалт 2029 оны хоёрдугаар сарын 7-нд болсон уу?',values),values)

    def test_explicit_day_and_unknown_publication_month_do_not_mix(self):
        one=dict(SOURCE,url='https://nmct.edu.mn/news/a',text='2029 оны 2 сарын 7 3 үзсэн')
        other=dict(one,url='https://nmct.edu.mn/news/b',text='2029 оны 2 сарын 8 4 үзсэн')
        values=[one,other]
        self.assertEqual(dated_news_evidence_sources('2029 оны 2 сарын 8-ны мэдээнд?',values),[other])
        self.assertEqual(dated_news_evidence_sources('2029 оны 9 сарын мэдээнд?',values),values)

    def setUp(self):
        self.first=dict(SOURCE,title='НАМРЫН ТУРШИЛТ – ХАМТЫН АЖИЛ',url='https://nmct.edu.mn/news/a')
        self.second=dict(SOURCE,title='Өөр үйл ажиллагаа',url='https://nmct.edu.mn/news/b')

    def test_unique_quoted_title_keeps_all_chunks_from_same_page(self):
        another=dict(self.first,source_id='web-another',title='Текстийн үргэлжлэл')
        values=[self.first,self.second,another]
        self.assertEqual(article_evidence_sources('«Намрын туршилт - хамтын ажил» мэдээнд ямар чадвар дурдсан бэ?',values),
                         [self.first,another])

    def test_repeated_title_does_not_guess_between_events(self):
        duplicate=dict(self.second,title=self.first['title'])
        values=[self.first,duplicate]
        self.assertEqual(article_evidence_sources('«Намрын туршилт – хамтын ажил» мэдээний үйл явдал?',values),values)

    def test_comparison_keeps_both_events(self):
        values=[self.first,self.second]
        self.assertEqual(article_evidence_sources('«Намрын туршилт – хамтын ажил» болон өөр мэдээг харьцуул.',values),values)

    def test_body_mentions_do_not_identify_article(self):
        other=dict(self.second,text='Намрын туршилт – хамтын ажил гэсэн холбоос байна.')
        values=[other]
        self.assertEqual(article_evidence_sources('«Намрын туршилт – хамтын ажил» мэдээнд?',values),values)

    def test_quoted_programme_heading_with_generic_page_title_can_identify_one_page(self):
        first=dict(self.first,title='Мэдээ',text='Бүх мэдээ\nМэдээ\n2029 оны мэдээ\n“Дижитал зун” хөтөлбөр – 2029\nСурагчид сургалтад оролцов.')
        self.assertEqual(article_evidence_sources('«Дижитал зун – 2029» хөтөлбөрийн мэдээнд?',
                         [first,self.second]),[first])


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'runtime').mkdir()
        self.config = self.root/'runtime/rag-model.json'
        self.config.write_text(json.dumps(dict(model='local-test',base_url='http://127.0.0.1:11434')))
        self.proposal = dict(insufficient=False, unit_ids=['u1'])
        self.requests = []

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, method, url, payload, timeout, max_bytes):
        self.requests.append((method,url,payload))
        if method == 'GET':
            return {'models':[{'name':'local-test:latest'}]}
        return {'done':True,'message':{'content':json.dumps(self.proposal,ensure_ascii=False)}}

    def generate(self):
        return GroundedGenerator(self.root,self.transport).generate('Төлбөр хэд вэ?', [SOURCE])

    def test_valid_evidence(self):
        r=self.generate()
        self.assertTrue(r['generated'])
        self.assertEqual(r['llm_calls'],1)
        self.assertEqual(r['claims'][0]['quote'],SOURCE['text'])

    def test_named_article_excludes_another_events_skill_before_generation(self):
        target=dict(SOURCE,title='Туршилтын намрын аян',text='Оюутнууд талбайн ургац хураав.')
        other=dict(SOURCE,source_id='web-other',url='https://nmct.edu.mn/news/other',
                   title='Өөр хөтөлбөр',text='Оюутнууд саадын зурвасаар дасгал хийв.')
        value=GroundedGenerator(self.root,self.transport).generate('«Туршилтын намрын аян» мэдээнд ямар ажил хийсэн бэ?', [target,other])
        self.assertTrue(value['generated'])
        self.assertEqual(value['article_scope_filter']['after'],[target['source_id']])
        sent=json.loads(self.requests[-1][2]['messages'][1]['content'])
        self.assertEqual([s['source_id'] for s in sent['SOURCES']],[target['source_id']])

    def test_invented_citation_rejected(self):
        self.proposal['unit_ids']=['invented']
        self.assertEqual(self.generate()['reason'],'unknown_evidence_unit')

    def test_model_authored_quote_not_accepted(self):
        self.proposal['quote']='Төлбөр үнэгүй болсон байна.'
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_invented_number_rejected(self):
        self.proposal=dict(insufficient=False,claims=[{'source_id':'web-test','text':'Сургалтын төлбөр 9,999,999 ₮.'}])
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_generator_year_mismatch_makes_no_provider_call(self):
        r=GroundedGenerator(self.root,self.transport).generate('2028 оны төлбөр?', [SOURCE])
        self.assertEqual(r['reason'],'requested_year_not_supported')
        self.assertFalse(self.requests)

    def test_question_is_not_accepted_as_answer(self):
        self.proposal['text']='Сургалтын төлбөр хэд вэ?'
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_insufficient_no_answer(self):
        self.proposal=dict(insufficient=True,unit_ids=[])
        self.assertFalse(self.generate()['generated'])

    def test_malformed_claim_rejected(self):
        self.proposal['unit_ids']=[123]
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_unconfigured_no_model_call(self):
        self.config.unlink()
        r=self.generate()
        self.assertFalse(r['generated'])
        self.assertEqual(r['llm_calls'],0)
        self.assertFalse(self.requests)

    def test_remote_origin_rejected(self):
        self.config.write_text(json.dumps(dict(model='local-test',base_url='http://example.com')))
        self.assertFalse(self.generate()['generated'])
        self.assertFalse(self.requests)

    def test_cloud_model_rejected(self):
        self.config.write_text(json.dumps(dict(model='local-test:cloud')))
        self.assertFalse(self.generate()['generated'])
        self.assertFalse(self.requests)

    def test_duplicate_selection_does_not_duplicate_a_claim(self):
        self.proposal['unit_ids']*=2
        self.assertFalse(self.generate()['generated'])

    def test_contradictory_insufficient_selection_rejected(self):
        self.proposal['insufficient']=True
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_prompt_data_is_structured(self):
        self.generate()
        p=self.requests[-1][2]
        self.assertIsInstance(p['format'],dict)
        self.assertEqual(json.loads(p['messages'][1]['content'])['SOURCES'][0]['source_id'],'web-test')
        self.assertIn('EVIDENCE_UNITS',json.loads(p['messages'][1]['content']))
        self.assertNotIn('page_header',json.loads(p['messages'][1]['content'])['SOURCES'][0])
        self.assertEqual(p['options']['seed'],42)
        self.assertEqual(self.generate()['claims'][0]['text'],SOURCE['text'])

    def field_selection(self, proposals, *, include_evaluation=True):
        """Exercise real field screens while replacing only local model I/O."""
        monitoring = 'Мониторинг\nӨдөр тутмын хэрэгжилтийг хянаж, дэмжин зөвлөх зорилготой.'
        evaluation = ('Үнэлгээ\nЗорилтын биелэлтийг тодорхой хугацааны давтамжтай '
                      'үнэлж сайжруулах зорилгоор хийнэ.')
        background = 'Ерөнхий журам\nЭнэ хуудсанд удирдлагын баримт бичгийн жагсаалтыг танилцуулсан.'
        texts = [monitoring, evaluation, background] if include_evaluation else [monitoring]
        text = '\n'.join(texts)
        source = dict(SOURCE, source_id='web-quality', text=text, excerpt=text,
                      title='Чанарын ойлголтууд', url='https://nmct.edu.mn/quality')
        posts = []
        responses = iter(proposals)

        def transport(method, url, payload, timeout, max_bytes):
            if method == 'GET':
                return {'models': [{'name': 'local-test:latest'}]}
            posts.append(copy.deepcopy(payload))
            proposal = next(responses)
            if isinstance(proposal, Exception):
                raise proposal
            return dict(done=True, prompt_eval_count=7, eval_count=3,
                        message=dict(content=json.dumps(proposal, ensure_ascii=False)))

        query = 'Мониторинг болон үнэлгээний зорилго, давтамжийг харьцуулна уу?'
        result = GroundedGenerator(self.root, transport).generate(query, [source])
        return result, posts, texts, source

    def test_missing_field_reselection_replaces_background_with_exact_source_units(self):
        result, posts, texts, source = self.field_selection([
            dict(insufficient=False, unit_ids=['u1', 'u3']),
            dict(insufficient=False, unit_ids=['u1', 'u2']),
        ])
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual([claim['text'] for claim in result['claims']], texts[:2])
        self.assertTrue(all(claim['quote'] == source['text'] for claim in result['claims']))
        self.assertEqual(result['missing_requested_fields'], [])
        self.assertEqual(result['selection_repair_reason'], 'literal_requested_field_omission')
        self.assertFalse(result['field_screen_semantic_correctness_proven'])
        self.assertFalse(result['semantic_correctness_proven'])
        self.assertEqual(result['provider_usage']['prompt_eval_count'], 14)
        self.assertEqual(result['provider_usage']['eval_count'], 6)
        first_data = json.loads(posts[0]['messages'][1]['content'])
        repair_data = json.loads(posts[1]['messages'][1]['content'])
        self.assertNotIn('SELECTION_REPAIR', first_data)
        self.assertEqual(repair_data['SELECTION_REPAIR']['previous_unit_ids'], ['u1', 'u3'])
        self.assertEqual(repair_data['SELECTION_REPAIR']['candidate_unit_ids'], {
            'monitoring_definition': ['u1'], 'monitoring_frequency': ['u1'],
            'evaluation_definition': ['u2'], 'evaluation_frequency': ['u2'],
        })
        self.assertEqual([u['unit_id'] for u in repair_data['EVIDENCE_UNITS']], ['u1', 'u2'])
        repaired_schema = posts[1]['format']['properties']['unit_ids']['anyOf']
        self.assertEqual(repaired_schema[0]['maxItems'], 0)  # Explicit abstention remains possible.
        self.assertEqual(repaired_schema[1]['items']['enum'], ['u1', 'u2'])
        self.assertEqual(repaired_schema[1]['minItems'], 2)
        self.assertEqual(result['selection_attempts'][0]['missing_fields'],
                         ['evaluation_definition', 'evaluation_frequency'])
        self.assertEqual(result['selection_attempts'][1]['missing_fields'], [])

    def test_complete_paired_field_selection_needs_only_one_call(self):
        result, posts, texts, _ = self.field_selection([
            dict(insufficient=False, unit_ids=['u1', 'u2']),
        ])
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'], 1)
        self.assertEqual(len(posts), 1)
        self.assertEqual([claim['text'] for claim in result['claims']], texts[:2])
        self.assertNotIn('selection_repair_reason', result)

    def test_persistent_field_omission_stops_after_second_call(self):
        result, posts, _, _ = self.field_selection([
            dict(insufficient=False, unit_ids=['u1']),
            dict(insufficient=False, unit_ids=['u1']),
        ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['reason'], 'requested_fields_not_in_selection')
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(len(posts), 2)
        self.assertEqual(result['missing_requested_fields'],
                         ['evaluation_definition', 'evaluation_frequency'])

    def test_missing_source_facet_stops_without_futile_second_call(self):
        result, posts, _, _ = self.field_selection([
            dict(insufficient=False, unit_ids=['u1']),
        ], include_evaluation=False)
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['reason'], 'requested_fields_not_in_evidence')
        self.assertEqual(result['llm_calls'], 1)
        self.assertEqual(len(posts), 1)

    def test_reselection_provider_failure_cannot_return_first_incomplete_answer(self):
        result, posts, _, _ = self.field_selection([
            dict(insufficient=False, unit_ids=['u1']), TimeoutError('local fixture timeout'),
        ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['reason'], 'provider_or_format_failure')
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(result['provider_usage_by_attempt']), 1)
        self.assertEqual(len(result['selection_attempts']), 2)
        self.assertEqual(result['selection_attempts'][1]['status'], 'provider_or_format_failure')

    def test_reselection_shares_generation_deadline_with_first_call(self):
        from unittest.mock import patch
        original_request = GroundedGenerator._request
        for first_seconds in (70, 105):
            with self.subTest(first_seconds=first_seconds):
                clock, timeouts = [0.0], []

                def request(instance, method, path, payload=None, timeout=10, *args, **kwargs):
                    if method == 'POST':
                        timeouts.append(timeout)
                    response = original_request(instance, method, path, payload, timeout, *args, **kwargs)
                    if method == 'POST':
                        clock[0] += first_seconds if len(timeouts) == 1 else 5
                    return response

                with patch('rag_runtime.time.perf_counter', side_effect=lambda: clock[0]), \
                        patch.object(GroundedGenerator, '_request', new=request):
                    result, _, _, _ = self.field_selection([
                        dict(insufficient=False, unit_ids=['u1']),
                        dict(insufficient=False, unit_ids=['u1', 'u2']),
                    ])
                self.assertEqual(timeouts[0], 60)
                if first_seconds == 70:
                    self.assertTrue(result['generated'])
                    self.assertEqual(timeouts, [60, 30])
                else:
                    self.assertFalse(result['generated'])
                    self.assertEqual(result['reason'], 'generation_deadline_exceeded')
                    self.assertEqual(result['llm_calls'], 1)
                    self.assertEqual(timeouts, [60])

    def test_reselection_rechecks_schema_opaque_ids_and_duplicate_guards(self):
        invalid = [
            (dict(insufficient=False, unit_ids=['u1', 'invented']), 'unknown_evidence_unit'),
            (dict(insufficient=False, unit_ids=['u1', 'u2'],
                  quote='Нэмэлт баталгаагүй хариулт'), 'invalid_generation'),
            (dict(insufficient=False, unit_ids=['u1', 'u1']), 'duplicate_evidence_selection'),
            (dict(insufficient=True, unit_ids=['u2']), 'invalid_generation'),
            (dict(insufficient=False, unit_ids=['u1', 2]), 'invalid_generation'),
        ]
        for proposal, reason in invalid:
            with self.subTest(proposal=proposal):
                result, posts, _, _ = self.field_selection([
                    dict(insufficient=False, unit_ids=['u1']), proposal,
                ])
                self.assertFalse(result['generated'])
                self.assertEqual(result['claims'], [])
                self.assertEqual(result['reason'], reason)
                self.assertEqual(result['llm_calls'], 2)
                self.assertEqual(len(posts), 2)

    def test_missing_code_marker_can_be_reselected_but_never_bypassed(self):
        text = ('CAD ашиглан зураг төсөл боловсруулах чадварыг эзэмшүүлэх зорилготой.\n'
                'CAM технологийг үйлдвэрлэлд ашиглах чадварыг эзэмшүүлэх зорилготой.')
        source = dict(SOURCE, text=text, excerpt=text)
        posts = []
        proposals = iter([dict(insufficient=False, unit_ids=['u1']),
                          dict(insufficient=False, unit_ids=['u1', 'u2'])])

        def transport(method, url, payload, timeout, max_bytes):
            if method == 'GET':
                return {'models': [{'name': 'local-test:latest'}]}
            posts.append(copy.deepcopy(payload))
            return dict(done=True, message=dict(content=json.dumps(next(proposals))))

        result = GroundedGenerator(self.root, transport).generate(
            'CAD болон CAM ямар өөр чадвартай холбож бичсэн бэ?', [source])
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual([c['text'] for c in result['claims']], text.splitlines())
        self.assertEqual(result['selection_attempts'][0]['missing_fields'], ['cam_objective'])
        self.assertNotIn('selection_diagnostics', result)
        self.assertIn('anchor:cam', result['selection_attempts'][0]['diagnostics']['missing_markers'])
        self.assertEqual(json.loads(posts[1]['messages'][1]['content'])['SELECTION_REPAIR']
                         ['candidate_unit_ids'], {'cad_objective': ['u1'], 'cam_objective': ['u2']})

    def library_reselection(self, replacement):
        partial = 'Номын сан\nLibX программыг 2032 оноос ашиглаж эхэлсэн.'
        complete = ('Номын сан 4275 номтой. LibX программыг 2032 оноос '
                    'ашиглаж эхэлсэн.')
        text = partial + '\n' + complete
        source = dict(SOURCE, text=text, excerpt=text, title='Номын сан',
                      url='https://nmct.edu.mn/library')
        self.assertEqual([unit['text'] for unit in evidence_units([source])], [partial, complete])
        posts = []
        proposals = iter([dict(insufficient=False, unit_ids=['u1']), replacement])

        def transport(method, url, payload, timeout, max_bytes):
            if method == 'GET':
                return {'models': [{'name': 'local-test:latest'}]}
            posts.append(copy.deepcopy(payload))
            return dict(done=True, message=dict(content=json.dumps(next(proposals))))

        result = GroundedGenerator(self.root, transport).generate(
            'Номын сангийн номын тоо болон LibX программыг ашиглаж эхэлсэн оныг хэлнэ үү.',
            [source])
        return result, posts, complete

    def test_single_unit_complete_repair_pool_excludes_partial_field_units(self):
        result, posts, complete = self.library_reselection(
            dict(insufficient=False, unit_ids=['u2']))
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual([claim['text'] for claim in result['claims']], [complete])
        self.assertEqual(result['selection_repair_minimum_units'], 1)
        data = json.loads(posts[1]['messages'][1]['content'])
        self.assertEqual([unit['unit_id'] for unit in data['EVIDENCE_UNITS']], ['u2'])
        self.assertEqual(data['SELECTION_REPAIR']['candidate_unit_ids'], {
            'library_stock_total': ['u2'], 'library_software_start_year': ['u2'],
        })
        branches = posts[1]['format']['properties']['unit_ids']['anyOf']
        self.assertTrue(all(branch['items']['enum'] == ['u2'] for branch in branches))
        self.assertEqual(branches[1]['minItems'], 1)

    def test_repair_cannot_add_known_unit_excluded_from_its_active_schema(self):
        result, posts, _ = self.library_reselection(
            dict(insufficient=False, unit_ids=['u1', 'u2']))
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(result['reason'], 'unknown_evidence_unit')
        self.assertEqual(len(posts), 2)

    def marker_selection(self, proposals, *, texts=None, query=None):
        """Invented source/code/year; transport never contacts a model."""
        texts = texts if texts is not None else [
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            '2037 онд өөр төслийн баг судалгааны ажилд оролцсон.',
            '2037 онд ZXQ9 төсөл туршилтын төхөөрөмж зохион бүтээсэн.',
        ]
        text = '\n'.join(texts)
        source = dict(SOURCE, source_id='invented-project-source', text=text, excerpt=text,
                      title='Туршилтын төслүүд', url='https://nmct.edu.mn/projects/fixture')
        posts, responses = [], iter(proposals)

        def transport(method, url, payload, timeout, max_bytes):
            if method == 'GET':
                return {'models': [{'name': 'local-test:latest'}]}
            posts.append(copy.deepcopy(payload))
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return dict(done=True, message=dict(content=(response if isinstance(response, str)
                        else json.dumps(response, ensure_ascii=False))))

        result = GroundedGenerator(self.root, transport).generate(
            query or '2037 оны ZXQ9 төслийн үйл ажиллагааг хэлнэ үү.', [source])
        return result, posts, texts

    def test_missing_marker_without_field_rule_reoffers_only_units_from_complete_options(self):
        result, posts, texts = self.marker_selection([
            dict(insufficient=False, unit_ids=['u1']),
            dict(insufficient=False, unit_ids=['u3']),
        ])
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'], 2)
        self.assertNotIn('requested_fields', result)
        self.assertEqual([claim['text'] for claim in result['claims']], [texts[2]])
        self.assertEqual(result['selection_repair_reason'], 'literal_requested_marker_omission')
        self.assertEqual(result['marker_selection_repair']['missing_markers'], ['anchor:2037'])
        self.assertEqual(result['marker_selection_repair']['candidate_selection_ids'], ['u1', 'u2', 'u3'])
        self.assertEqual(result['marker_selection_repair']['admissible_selection_options'],
                         [['u3'], ['u1', 'u2'], ['u1', 'u3']])
        self.assertEqual(result['marker_selection_repair']['status'], 'accepted')
        self.assertEqual(len(result['selection_attempts']), 2)
        data = json.loads(posts[1]['messages'][1]['content'])
        self.assertEqual([unit['unit_id'] for unit in data['EVIDENCE_UNITS']], ['u1', 'u2', 'u3'])
        self.assertEqual([unit['text'] for unit in data['EVIDENCE_UNITS']], texts)
        self.assertEqual(data['ADMISSIBLE_SELECTION_OPTIONS'], [['u3'], ['u1', 'u2'], ['u1', 'u3']])
        self.assertNotIn('REQUESTED_FIELDS', data)
        branches = posts[1]['format']['properties']['unit_ids']['anyOf']
        self.assertEqual(branches[0]['maxItems'], 0)
        self.assertEqual(branches[1]['minItems'], 1)
        self.assertEqual(branches[1]['maxItems'], 2)

    def test_missing_markers_need_three_complementary_units_so_no_pair_retry(self):
        result, posts, _ = self.marker_selection([dict(insufficient=False, unit_ids=['u1'])], texts=[
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            '2037 онд өөр төслийн баг судалгааны ажилд оролцсон.',
            'PQR8 төсөл судалгааны тоног төхөөрөмжийг шинэчилсэн.',
        ], query='2037 оны ZXQ9 болон PQR8 төслийн үйл ажиллагааг хэлнэ үү.')
        self.assertFalse(result['generated'])
        self.assertEqual(result['reason'], 'requested_evidence_markers_missing')
        self.assertEqual(len(posts), 1)
        self.assertEqual(result['marker_selection_repair']['candidate_unit_ids'], [])
        self.assertEqual(result['marker_selection_repair']['status'], 'not_attempted_no_admissible_option')

    def test_two_partial_units_can_form_one_complete_anchored_pair_in_either_order(self):
        for replacement in [['u1', 'u2'], ['u2', 'u1']]:
            with self.subTest(replacement=replacement):
                result, posts, texts = self.marker_selection([
                    dict(insufficient=False, unit_ids=['u1']),
                    dict(insufficient=False, unit_ids=replacement),
                ], texts=[
                    'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
                    '2037 онд өөр төслийн баг судалгааны ажилд оролцсон.',
                ])
                self.assertTrue(result['generated'])
                self.assertEqual(result['llm_calls'], 2)
                self.assertEqual(set(claim['text'] for claim in result['claims']), set(texts))
                self.assertEqual(result['selection_repair_minimum_units'], 2)
                data = json.loads(posts[1]['messages'][1]['content'])
                self.assertEqual(data['ADMISSIBLE_SELECTION_OPTIONS'], [['u1', 'u2']])

    def test_missing_query_code_not_present_in_evidence_is_not_new_repair_rule(self):
        result, posts, _ = self.marker_selection([dict(insufficient=False, unit_ids=['u1'])],
            query='UNSEEN7 төслийн тухай хэлнэ үү.',
            texts=['Төслийн баг лабораторийн хамтын ажиллагааг өргөжүүлсэн.'])
        self.assertTrue(result['generated'])  # Unchanged literal-marker contract.
        self.assertEqual(len(posts), 1)
        self.assertNotIn('marker_selection_repair', result)

    def test_marker_retry_can_explicitly_abstain_without_reusing_first_answer(self):
        result, posts, _ = self.marker_selection([
            dict(insufficient=False, unit_ids=['u1']), dict(insufficient=True, unit_ids=[]),
        ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['reason'], 'insufficient_evidence')
        self.assertEqual(result['marker_selection_repair']['status'], 'insufficient_evidence')
        self.assertEqual(len(posts), 2)

    def test_marker_retry_unknown_or_excluded_unit_stops_after_two_calls(self):
        for second in ['unknown', 'u1']:
            with self.subTest(second=second):
                result, posts, _ = self.marker_selection([
                    dict(insufficient=False, unit_ids=['u1']),
                    dict(insufficient=False, unit_ids=[second]),
                ])
                self.assertFalse(result['generated'])
                self.assertEqual(result['claims'], [])
                reason = 'unknown_evidence_unit' if second == 'unknown' else 'invalid_evidence_selection'
                self.assertEqual(result['reason'], reason)
                self.assertEqual(result['marker_selection_repair']['status'], reason)
                self.assertEqual(len(posts), 2)

    def test_marker_retry_rejects_two_allowed_ids_from_an_unanchored_pair(self):
        result, posts, _ = self.marker_selection([
            dict(insufficient=False, unit_ids=['u1']),
            dict(insufficient=False, unit_ids=['u3', 'u4']),
        ], texts=[
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            '2037 онд өөр төслийн баг судалгааны ажилд оролцсон.',
            '2037 онд ZXQ9 төсөл туршилтын төхөөрөмж зохион бүтээсэн.',
            '2037 онд ZXQ9 төсөл хамтарсан сургалтын туршилт явуулсан.',
        ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['reason'], 'invalid_evidence_selection')
        self.assertEqual(result['marker_selection_repair']['candidate_selection_ids'], ['u1', 'u2', 'u3', 'u4'])
        self.assertEqual(len(posts), 2)

    def test_marker_retry_rejects_out_of_option_union_duplicates_and_more_than_two_ids(self):
        for replacement in [['u2', 'u3'], ['u3', 'u3'], ['u1', 'u2', 'u3']]:
            with self.subTest(replacement=replacement):
                result, posts, _ = self.marker_selection([
                    dict(insufficient=False, unit_ids=['u1']),
                    dict(insufficient=False, unit_ids=replacement),
                ])
                self.assertFalse(result['generated'])
                self.assertEqual(result['claims'], [])
                self.assertEqual(result['reason'], 'invalid_generation' if len(replacement) > 2
                                 else 'invalid_evidence_selection')
                self.assertEqual(len(posts), 2)

    def test_marker_candidate_must_pass_original_exact_span_guard(self):
        def corrupt_complete_source(sources, **kwargs):
            units = evidence_units(sources, **kwargs)
            units[2]['start'] += 1
            return units

        with patch('rag_runtime.evidence_units', side_effect=corrupt_complete_source):
            result, posts, _ = self.marker_selection([dict(insufficient=False, unit_ids=['u1'])], texts=[
                'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
                'Өөр төслийн баг судалгааны ажилд хамтран оролцсон.',
                '2037 онд ZXQ9 төсөл туршилтын төхөөрөмж зохион бүтээсэн.',
            ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['reason'], 'requested_evidence_markers_missing')
        self.assertEqual(result['marker_selection_repair']['candidate_unit_ids'], [])
        self.assertEqual(len(posts), 1)

    def test_marker_repair_unit_limit_stops_without_second_call(self):
        result, posts, _ = self.marker_selection([dict(insufficient=False, unit_ids=['u1'])], texts=[
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            *[f'2037 онд ZXQ9 төсөл {index} дугаар төхөөрөмжийг туршсан.' for index in range(64)],
        ])
        self.assertFalse(result['generated'])
        self.assertEqual(result['evidence_unit_count'], 65)
        self.assertEqual(result['marker_selection_repair']['status'], 'not_attempted_unit_limit')
        self.assertEqual(result['marker_selection_repair']['admissible_selection_options'], [])
        self.assertEqual(len(posts), 1)

    def test_marker_repair_option_limit_never_offers_truncated_options(self):
        result, posts, _ = self.marker_selection([dict(insufficient=False, unit_ids=['u1'])], texts=[
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            *[f'2037 онд ZXQ9 төсөл {index} дугаар төхөөрөмжийг туршсан.' for index in range(33)],
        ])
        self.assertFalse(result['generated'])
        repair = result['marker_selection_repair']
        self.assertEqual(repair['status'], 'not_attempted_option_limit')
        self.assertEqual(repair['observed_option_count'], 33)
        self.assertEqual(repair['admissible_selection_options'], [])
        self.assertEqual(len(posts), 1)

    def test_marker_repair_exactly_thirty_two_options_still_allows_retry(self):
        result, posts, _ = self.marker_selection([
            dict(insufficient=False, unit_ids=['u1']), dict(insufficient=False, unit_ids=['u2']),
        ], texts=[
            'ZXQ9 төсөл лабораторийн хамтын ажиллагааг өргөжүүлсэн.',
            *[f'2037 онд ZXQ9 төсөл {index} дугаар төхөөрөмжийг туршсан.' for index in range(16)],
        ])
        self.assertTrue(result['generated'])
        self.assertEqual(result['marker_selection_repair']['observed_option_count'], 32)
        self.assertEqual(len(posts), 2)

    def test_marker_repair_does_not_retry_first_provider_or_json_failures(self):
        for response in [TimeoutError('fixture'), '{invalid json', dict(insufficient='no', unit_ids=['u1'])]:
            with self.subTest(response=str(response)):
                result, posts, _ = self.marker_selection([response])
                self.assertFalse(result['generated'])
                self.assertEqual(result['llm_calls'], 1)
                self.assertEqual(len(posts), 1)
                self.assertNotIn('marker_selection_repair', result)


class Policy:
    enabled=True
    def __init__(self,reason='no_supported_question_match',answer=None):
        self.reason,self.answer=reason,answer
    def route(self,db,query,allow_draft=False):
        return dict(query=query,route='E',package_id='package1',reason_code=self.reason,
            reason_codes=[self.reason],answer=self.answer,citations=[],clarification=None,
            exact_matches=[],generated=False,llm_calls=0,message='no',answer_kind=None)


class Retriever:
    def __init__(self):
        self.corpus_id='corpus1'
        self.sources=[copy.deepcopy(SOURCE)]
        self.calls=0
    def status(self):
        return dict(available=True,corpus_id=self.corpus_id)
    def search(self,q,limit=4):
        self.calls+=1
        return dict(candidates=self.sources,corpus_id=self.corpus_id,backend='test')


class Generator:
    def __init__(self):
        self.calls=0
    def status(self):
        return dict(available=True)
    def generate(self,q,sources):
        self.calls+=1
        return dict(generated=True,llm_calls=1,claims=[copy.deepcopy(CLAIM)],reason='test')


class NamedLaboratoryExtractTests(unittest.TestCase):
    def setUp(self):
        self.query = ('Фотоник инженерийн тэнхим ямар үндсэн лабораторитой, '
                      'нэг удаад хэдэн оюутан ажиллах боломжтой вэ?')
        self.paragraph = ('Лаборатори, сургалтын орчин\n'
                          'Тэнхим нь спектрийн лаборатори, оптикийн лаборатори гэсэн '
                          'хоёр үндсэн лабораторитой. Нэг удаад 8–14 оюутан ажиллах боломжтой.')
        self.mission = 'Тэнхимийн эрхэм зорилго\nТус тэнхим бүтээлч инженер бэлтгэх зорилготой.'
        text = self.mission + '\n' + self.paragraph
        self.source = dict(SOURCE, source_id='synthetic-photonics', text=text, excerpt=text,
                           title='Фотоник инженерийн тэнхим',
                           url='https://nmct.edu.mn/departments/photonics')

    def test_named_inventory_and_session_capacity_copies_one_exact_source_unit(self):
        selected = focused_extract(self.query, [self.source])
        self.assertEqual(selected, (self.source, self.paragraph))
        self.assertIn(selected[1], self.source['text'])
        self.assertNotIn(self.mission, selected[1])
        self.assertIn('8–14', selected[1])

    def test_ambiguous_other_department_comparison_and_single_attribute_stay_general(self):
        for query in [
            'Тэнхим ямар үндсэн лабораторитой, нэг удаад хэдэн оюутан ажиллах боломжтой вэ?',
            self.query.replace('Фотоник', 'Роботик'),
            self.query.replace('Фотоник инженерийн тэнхим',
                               'Фотоник инженерийн тэнхим болон Роботик инженерийн тэнхим'),
            self.query + ' Бусад тэнхимтэй харьцуулна уу.',
            'Фотоник инженерийн тэнхимийн лабораторид нэг удаад хэдэн оюутан ажиллах боломжтой вэ?',
            'Фотоник инженерийн тэнхим ямар үндсэн лабораторитой вэ?',
            '2029 оны ' + self.query,
            self.query.replace('хэдэн оюутан', 'хэдэн гадаад оюутан'),
            self.query.replace('хэдэн оюутан', 'хэдэн нэгдүгээр курсийн оюутан'),
            self.query.replace('үндсэн лабораторитой', 'үндсэн CNC лабораторитой'),
            self.query.replace('Фотоник инженерийн тэнхим', 'Фотоник инженерийн тэнхим ба Роботик'),
            self.query.replace('нэг удаад', 'өнөөдөр нэг удаад'),
        ]:
            with self.subTest(query=query):
                self.assertIsNone(focused_extract(query, [self.source]))

    def test_source_must_have_explicit_inventory_and_student_capacity_together(self):
        for text in [
            'Тэнхим нь спектрийн лаборатори, оптикийн лаборатори гэсэн хоёр үндсэн лабораторитой.',
            'Лабораторид нэг удаад 8–14 оюутан ажиллах боломжтой.',
            'Тэнхим хоёр лабораторитой. Нэг удаад 8–14 оюутан ажиллах боломжтой.',
            'Спектрийн лаборатори, оптикийн лабораторитой. Нийт 48 оюутан суралцдаг.',
            self.paragraph.replace('боломжтой', 'боломжгүй'),
            self.paragraph.replace('боломжтой', 'боломжтой биш'),
            self.paragraph.replace('боломжтой', 'боломжтой эсэх тодорхойгүй'),
            ('Спектрийн лаборатори, оптикийн лабораторитой.\n'
             'Нэг удаад 8–14 оюутан ажиллах боломжтой.'),
        ]:
            with self.subTest(text=text):
                source = dict(self.source, text=text, excerpt=text)
                self.assertIsNone(focused_extract(self.query, [source]))

    def test_conflicting_qualifying_paragraphs_do_not_choose_first_amount(self):
        changed = self.paragraph.replace('8–14', '11–17')
        other = dict(self.source, source_id='synthetic-photonics-other', text=changed, excerpt=changed)
        self.assertIsNone(focused_extract(self.query, [self.source, other]))
        duplicate = dict(other, text=self.paragraph, excerpt=self.paragraph)
        self.assertEqual(focused_extract(self.query, [self.source, duplicate])[1], self.paragraph)

    def test_direct_route_keeps_source_and_prior_year_live_guards(self):
        retriever, generator = Retriever(), Generator()
        retriever.sources = [self.source]
        chat = ChatRAG('.', Policy(), retriever, generator)
        result = chat.route(None, self.query)
        self.assertEqual(result['route'], 'A')
        self.assertEqual(result['llm_calls'], 0)
        self.assertIn(self.paragraph, result['answer'])
        self.assertNotIn(self.mission, result['answer'])
        self.assertEqual(result['citations'][0]['document_id'], self.source['source_id'])
        for query, reason in [
            ('2029 оны ' + self.query, 'requested_year_not_supported'),
            (self.query.replace('нэг удаад', 'өнөөдөр нэг удаад'), 'live_status_not_supported'),
        ]:
            value = chat.route(None, query)
            self.assertIsNone(value['answer'])
            self.assertEqual(value['reason_code'], reason)
        self.assertEqual(generator.calls, 0)


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.retriever=Retriever()
        self.generator=Generator()
        self.policy=Policy()
        self.chat=ChatRAG('.',self.policy,self.retriever,self.generator)

    def test_c_citations_and_cache(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        self.assertEqual(r['route'],'C')
        self.assertIn('[1]',r['answer'])
        self.assertEqual(r['citations'][0]['source_url_or_filename'],SOURCE['url'])
        self.assertEqual(self.chat.recall(r['response_id'],r['query'],r['package_id'],False)['answer'],r['answer'])
        self.assertEqual(self.generator.calls,1)

    def test_document_citation_keeps_locator_and_transcription_method(self):
        self.retriever.sources[0].update(url='https://nmct.edu.mn/rule.png',
            source_locator='х.2, IV.6', extraction_method='visual_transcription', reviewer_kind='assistant')
        result=self.chat.route(None,'Төлбөр хэд вэ?')
        citation=result['citations'][0]
        self.assertEqual(citation['locator'],'х.2, IV.6')
        self.assertEqual(citation['extraction_method'],'visual_transcription')
        self.assertEqual(citation['reviewer_kind'],'assistant')
        self.assertFalse(citation['school_staff_approval'])

    def test_provider_failure_does_not_claim_evidence_missing(self):
        self.generator.generate=lambda q,s: dict(generated=False,llm_calls=1,claims=[],reason='provider_or_format_failure')
        result=self.chat.route(None,'Төлбөр хэд вэ?')
        self.assertEqual(result['reason_code'],'generation_unavailable_with_sources')
        self.assertTrue(result['related_sources'])
        self.assertIn('саатал',result['message'])
        self.assertEqual(result['suggestions'][0],result['query'])
        self.assertIsNone(result['answer'])

    def test_cache_mismatch(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        for query,package,draft in [('өөр','package1',False),(r['query'],'other',False),(r['query'],'package1',True)]:
            with self.assertRaises(ValueError):
                self.chat.recall(r['response_id'],query,package,draft)

    def test_changed_corpus_invalidates_audio(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        self.retriever.corpus_id='changed'
        with self.assertRaises(ValueError):
            self.chat.recall(r['response_id'],r['query'],'package1',False)

    def test_guards_never_bypassed(self):
        for reason in ['expired_content','future_validity','partial_answer','unsupported_year',
                       'live_status_not_supported','specific_scope_not_supported','missing_year',
                       'content_rejected_or_unapproved','unmatched_numeric_constraints']:
            self.policy.reason=reason
            r=self.chat.route(None,'Асуулт')
            self.assertEqual(r['reason_code'],reason)
        self.assertEqual(self.retriever.calls,0)
        self.assertEqual(self.generator.calls,0)

    def test_disabled_policy_never_uses_web(self):
        self.policy.enabled=False
        self.chat.route(None,'Асуулт')
        self.assertEqual(self.retriever.calls,0)

    def test_direct_answer_no_llm(self):
        self.policy.answer='Эхтэй бэлэн хариулт'
        self.assertEqual(self.chat.route(None,'Асуулт')['answer'],self.policy.answer)
        self.assertEqual(self.generator.calls,0)

    def test_greeting_no_search(self):
        r=self.chat.route(None,'Сайн байна уу?')
        self.assertEqual(r['route'],'D')
        self.assertTrue(r['suggestions'])
        self.assertEqual(self.retriever.calls,0)

    def test_external_sources_excluded(self):
        self.retriever.sources[0]['url']='https://nmct.edu.mn.evil/elselt'
        r=self.chat.route(None,'Асуулт')
        self.assertIsNone(r['answer'])
        self.assertFalse(r['related_sources'])
        self.assertEqual(self.generator.calls,0)

    def test_live_request_sources_only(self):
        r=self.chat.route(None,'Одоо бүртгэл нээлттэй юу?')
        self.assertIsNone(r['answer'])
        self.assertEqual(r['reason_code'],'live_status_not_supported')
        self.assertEqual(self.generator.calls,0)
        self.assertTrue(r['related_sources'])

    def test_new_year_not_replaced(self):
        r=self.chat.route(None,'2028 оны төлбөр хэд вэ?')
        self.assertIsNone(r['answer'])
        self.assertEqual(self.generator.calls,0)

    def test_no_sources_has_next_steps(self):
        self.retriever.sources=[]
        r=self.chat.route(None,'Ангараг дээр муур бий юу?')
        self.assertTrue(r['message'])
        self.assertTrue(r['suggestions'])
        self.assertFalse(r['generated'])

    def test_empty_topic_clarifies_without_search(self):
        for query in ['???','Сургуулийн тухай мэдээлэл']:
            self.assertEqual(self.chat.route(None,query)['reason_code'],'clarify_topic')
        self.assertEqual(self.retriever.calls,0)

    def test_fee_extract_copies_source_but_not_other_fee_scope(self):
        s=copy.deepcopy(SOURCE)
        direct=source_extract('Сургалтын төлбөр хэд вэ?',[s])
        self.assertEqual(direct[1],s['text'])
        for q in ['Олимпиадын төлбөр хэд вэ?','Гадаад оюутны сургалтын төлбөр хэд вэ?',
                  'Сургалтын төлбөрийн хөнгөлөлт бий юу?']:
            self.assertIsNone(source_extract(q,[s]))

    def test_how_to_enroll_is_not_replaced_by_eligibility(self):
        s=copy.deepcopy(SOURCE)
        s['text']='Элсэлтэд оролцох эрх\nЕБС-ийн 9 дүгээр ангиа төгссөн сурагч\nХолбоо барих'
        self.assertIsNone(source_extract('Яаж элсэх вэ?',[s]))
        self.assertIsNotNone(source_extract('Элсэхэд ямар шаардлагатай вэ?',[s]))

    def test_registration_steps_are_copied_without_changing_scope(self):
        s=copy.deepcopy(SOURCE)
        steps='1. Бүртгүүлэх\nМэдээллээ бөглөнө.\n2. Хураамж төлөх\nQPay ашиглана.\n3. Хувийн хэсэг\nБүртгэлийн мэдээллээ харна.'
        s['text']='Элсэлт 2026\n'+steps+'\nСонгох мэргэжил'
        self.assertEqual(source_extract('Элсэлтийн бүртгэлд ямар алхмууд байдаг вэ?',[s])[1],steps)
        self.assertEqual(source_extract('Яаж элсэх вэ?',[s])[1],steps)
        self.assertIsNone(source_extract('Гадаад оюутан яаж элсэх вэ?',[s]))

    def test_kosen_news_does_not_answer_general_concept(self):
        self.retriever.sources[0]['url']='https://nmct.edu.mn/news/kis-meeting'
        r=self.chat.route(None,'Коосэн сургалтын онцлог юу вэ?')
        self.assertEqual(r['reason_code'],'concept_overview_not_supported')
        self.assertEqual(self.generator.calls,0)
        self.assertTrue(r['related_sources'])

    def test_direct_extract_retains_source_year_and_capture_date(self):
        self.retriever.sources[0]['page_header']='ШМТК — Элсэлт 2026\nАлбан эх'
        r=self.chat.route(None,'Сургалтын төлбөр хэд вэ?')
        self.assertEqual(r['route'],'A')
        self.assertIn('2026-10-10',r['answer'])
        self.assertIn('Элсэлт 2026',r['answer'])
        self.assertFalse(r['generated'])
        self.assertEqual(self.generator.calls,0)

if __name__=='__main__':
    unittest.main()
