"""Synthetic unit cases for bounded D reply capabilities; no model calls."""
import threading
import unittest

from clarification_context import ClarificationContext, ClarificationConflict


class Clock:
    now = 10.0
    def __call__(self): return self.now


def fee(query="Бүртгэлийн хураамж хэд вэ?"):
    return dict(query=query, route="D", answer=None, package_id="package-one",
                rag={"corpus_id": "corpus-one"}, reason_code="registration_scope_ambiguous",
                suggestions=["Элсэлтийн бүртгэлийн хураамж хэд вэ?",
                             "Олимпиадын бүртгэлийн хураамж хэд вэ?"])


class ClarificationContextTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.context = ClarificationContext(clock=self.clock)

    def resolve(self, token, reply, **kwargs):
        bindings = dict(allow_draft=False, package_id="package-one", corpus_id="corpus-one")
        bindings.update(kwargs)
        return self.context.resolve(token, reply, **bindings)

    def test_admission_short_reply_is_existing_full_choice(self):
        token = self.context.issue(fee())
        result = self.resolve(token, "Элсэлтийнх")
        self.assertEqual(result["raw_query"], "Элсэлтийнх")
        self.assertEqual(result["resolved_query"], fee()["suggestions"][0])
        self.assertTrue(result["applied"])
        self.assertEqual(result["reason"], "supported_reply")

    def test_olympiad_alias_and_literal_option(self):
        for reply in ("ОЛИМПИАДЫНХ!", fee()["suggestions"][1]):
            result = self.resolve(self.context.issue(fee()), reply)
            self.assertEqual(result["resolved_query"], fee()["suggestions"][1])

    def test_unknown_and_new_topic_are_fresh_not_fuzzy(self):
        for reply in ("Элсэлтййнх", "Элсэлтийнх гэхдээ 2027", "Паспорт яаж сунгах вэ?", "Элсэлтийнх биш"):
            token = self.context.issue(fee())
            result = self.resolve(token, reply)
            self.assertFalse(result["applied"])
            self.assertEqual(result["resolved_query"], reply)
            self.assertEqual(result["reason"], "unrecognized_reply")
            with self.assertRaises(ClarificationConflict): self.resolve(token, "Элсэлтийнх")

    def test_capability_is_one_shot(self):
        token = self.context.issue(fee())
        self.resolve(token, "Элсэлтийнх")
        with self.assertRaises(ClarificationConflict): self.resolve(token, "Олимпиадынх")

    def test_only_one_thread_can_consume_capability(self):
        token = self.context.issue(fee())
        outcomes = []
        def resolve():
            try: outcomes.append(self.resolve(token, "Элсэлтийнх")["applied"])
            except ClarificationConflict: outcomes.append(False)
        threads = [threading.Thread(target=resolve) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(outcomes.count(True), 1)

    def test_expiry_boundary_and_unknown_id_fail(self):
        token = self.context.issue(fee())
        self.clock.now += 300
        with self.assertRaises(ClarificationConflict): self.resolve(token, "Элсэлтийнх")
        with self.assertRaises(ClarificationConflict): self.resolve("f" * 32, "Элсэлтийнх")

    def test_binding_mismatches_fail_and_consume(self):
        for changed in (dict(package_id="new"), dict(corpus_id="new"), dict(allow_draft=True)):
            token = self.context.issue(fee())
            with self.assertRaises(ClarificationConflict): self.resolve(token, "Элсэлтийнх", **changed)
            with self.assertRaises(ClarificationConflict): self.resolve(token, "Элсэлтийнх")

    def test_capacity_evicts_oldest_only(self):
        context = ClarificationContext(max_entries=2, clock=self.clock)
        tokens = [context.issue(fee()) for _ in range(3)]
        with self.assertRaises(ClarificationConflict):
            context.resolve(tokens[0], "Элсэлтийнх", allow_draft=False, package_id="package-one", corpus_id="corpus-one")
        self.assertEqual(context.reset([tokens[1]]), {"removed": 1})
        self.assertEqual(context.reset([tokens[2]]), {"removed": 1})

    def test_reset_only_given_tokens_idempotent_and_validates(self):
        first, second = self.context.issue(fee()), self.context.issue(fee())
        self.assertEqual(self.context.reset([first, first, "f" * 32]), {"removed": 1})
        self.assertEqual(self.context.reset([first]), {"removed": 0})
        self.assertTrue(self.resolve(second, "Элсэлтийнх")["applied"])
        for invalid in (None, "abc", [None], ["/../../"], ["f" * 32] * 65):
            with self.assertRaises(ValueError): self.context.reset(invalid)

    def test_original_year_is_preserved(self):
        result = self.resolve(self.context.issue(fee("2026 оны бүртгэлийн хураамж хэд вэ?")), "Элсэлтийнх")
        self.assertEqual(result["resolved_query"], "2026 оны " + fee()["suggestions"][0])

    def test_original_year_range_is_preserved(self):
        original = fee("2025–2026 оны бүртгэлийн хураамж хэд вэ?")
        result = self.resolve(self.context.issue(original), "Олимпиадынх")
        self.assertTrue(result["resolved_query"].startswith("2025–2026 оны "))

    def test_conflicting_suggestion_year_is_not_offered_for_resolution(self):
        original = fee("2027 оны бүртгэлийн хураамж хэд вэ?")
        original["suggestions"] = ["2026 оны " + text for text in original["suggestions"]]
        self.assertIsNone(self.context.issue(original))

    def test_category_does_not_infer_a_year_from_option(self):
        original = fee()
        original["suggestions"] = ["2026 оны " + text for text in original["suggestions"]]
        result = self.resolve(self.context.issue(original), "Элсэлтийнх")
        self.assertFalse(result["applied"])
        full = original["suggestions"][0]
        self.assertTrue(self.resolve(self.context.issue(original), full)["applied"])

    def test_unsafe_negation_numeric_entity_constraints_never_disappear(self):
        for query in ("Бүртгэлийн хураамж төлөхгүй бол хэд вэ?", "Бүртгэлийн хураамж 50000 төгрөг үү?",
                      "SQL бүртгэлийн хураамж хэд вэ?", "Ярилцлагын бүртгэлийн хураамж хэд вэ?"):
            with self.subTest(query=query): self.assertIsNone(self.context.issue(fee(query)))

    def test_missing_year_accepts_only_listed_year_and_range(self):
        original = dict(query="ARC-д ямар хичээл ордог вэ?", route="D", answer=None,
            package_id="package-one", clarification={"kind": "missing_year", "supported_years": ["2023", "2024"],
                "options": [{"question": "2023–2024 оны ARC-д ямар хичээл ордог вэ?"}]})
        for reply in ("2023", "2024 онд", "2023-2024 оны"):
            result = self.resolve(self.context.issue(original), reply)
            self.assertTrue(result["applied"])
            self.assertIn("ARC", result["resolved_query"])
            self.assertTrue(result["resolved_query"].startswith(reply.replace(" онд", "").replace(" оны", "") + " оны "))
        for reply in ("2027", "2024-2023", "2023 бусад", "2023 эсвэл 2027"):
            self.assertFalse(self.resolve(self.context.issue(original), reply)["applied"])

    def test_ambiguous_alias_does_not_choose_arbitrarily(self):
        original = fee("Шалгалт хэдэн минут вэ?")
        original["suggestions"] = ["Элсэлтийн бичгийн шалгалт хэдэн минут вэ?", "Элсэлтийн ярилцлагын шалгалт хэдэн минут вэ?"]
        self.assertFalse(self.resolve(self.context.issue(original), "Элсэлтийнх")["applied"])
        self.assertTrue(self.resolve(self.context.issue(original), "Бичгийнх")["applied"])

    def test_unlisted_qualifiers_cannot_disappear(self):
        for query in ("Бүртгэлийн хураамж сар бүр хэд вэ?", "Өмнөх жилийн бүртгэлийн хураамж хэд вэ?",
                      "Гадаадын иргэний бүртгэлийн хураамж хэд вэ?", "Бүртгэлийн хураамж банканд хэд вэ?",
                      "Бүртгэлийн хураамж ямар хугацаа вэ?", "Бүртгэлийн хураамж хэр удаан вэ?"):
            with self.subTest(query=query): self.assertIsNone(self.context.issue(fee(query)))

    def test_qualifiers_preserved_in_same_choice_remain_usable(self):
        original = fee("Бүртгэлийн хураамж сар бүр хэд вэ?")
        original["suggestions"] = ["Элсэлтийн бүртгэлийн хураамж сар бүр хэд вэ?",
                                   "Олимпиадын бүртгэлийн хураамж сар бүр хэд вэ?"]
        self.assertIn("сар бүр", self.resolve(self.context.issue(original), "Элсэлтийнх")["resolved_query"])

    def test_exam_duration_word_form_resolves_to_listed_minutes_choice(self):
        original = fee("Шалгалтын хугацаа хэр удаан вэ?")
        original["suggestions"] = ["Ярилцлагын шалгалт хэдэн минут вэ?", "Бичгийн шалгалт хэдэн минут вэ?"]
        result = self.resolve(self.context.issue(original), "Ярилцлагынх")
        self.assertEqual(result["resolved_query"], original["suggestions"][0])

    def test_result_mutation_cannot_change_issued_choices(self):
        original = fee()
        token = self.context.issue(original)
        original["suggestions"][0] = "Өөр шинэ асуулт"
        self.assertEqual(self.resolve(token, "Элсэлтийнх")["resolved_query"], fee()["suggestions"][0])

    def test_no_capabilities_for_non_d_empty_or_answered_results(self):
        for change in (dict(route="A"), dict(suggestions=[]), dict(answer="answer")):
            original = fee()
            original.update(change)
            self.assertIsNone(self.context.issue(original))

    def test_malformed_id_rejected(self):
        for token in (None, "", "ABC" * 10, "a" * 33):
            with self.assertRaises(ValueError): self.resolve(token, "Элсэлтийнх")

    def cooperation(self, query='ТанигдаагүйНэр компанийн хамтын ажиллагаа хэдэн сараас эхэлсэн, ямар платформ ашигласан бэ?'):
        return dict(query=query, route='D', answer=None, package_id='package-one',
                    rag={'corpus_id': 'corpus-one'}, suggestions=['Холбоо барих утас хэд вэ?'],
                    clarification=dict(kind='missing_cooperation_entity', options=[
                        dict(question='Sakura Internet', entity='Sakura Internet'),
                        dict(question='ARC', entity='ARC'), dict(question='StoD', entity='StoD')]))

    def test_partner_choice_preserves_original_month_platform_and_raw_words(self):
        for partner in ('Sakura Internet', 'Sakura', 'ARC', 'StoD'):
            original=self.cooperation()
            reply=self.resolve(self.context.issue(original), partner)
            entity='Sakura Internet' if partner=='Sakura' else partner
            self.assertEqual(reply['resolved_query'], original['query']+'\nХамтын ажиллагааны байгууллага: '+entity)
            self.assertTrue(reply['applied'])
            self.assertIn('ТанигдаагүйНэр',reply['resolved_query'])

    def test_partner_selection_keeps_unknown_qualifiers_dates_numbers_and_negation(self):
        query='2024–2025 оны 7-р сард эхлээгүй бол зөвхөн оройн ангийн ямар платформ ашиглах вэ?'
        reply=self.resolve(self.context.issue(self.cooperation(query)), 'StoD')
        self.assertEqual(reply['resolved_query'],query+'\nХамтын ажиллагааны байгууллага: StoD')

    def test_partner_choice_does_not_erase_explicit_other_entity(self):
        for query in ('Sakura биш өөр компанийн платформ юу вэ?', 'ARC болон StoD-ийг харьцуулна уу.'):
            self.assertIsNone(self.context.issue(self.cooperation(query)))

    def test_partner_choice_accepts_only_offered_unique_literal_entities(self):
        original=self.cooperation(); original['clarification']['options']=original['clarification']['options'][:1]
        for reply in ('StoD','Sakura биш','Sakura 2027','Холбоо барих утас хэд вэ?'):
            result=self.resolve(self.context.issue(original), reply)
            self.assertFalse(result['applied'])
            self.assertEqual(result['resolved_query'], reply)
        original['clarification']['options']=[dict(question='Mystery', entity='Mystery')]
        self.assertIsNone(self.context.issue(original))


if __name__ == "__main__": unittest.main()


class ClarifiedFeeSourceTests(unittest.TestCase):
    def test_literal_html_amount_keeps_source_without_hardcoded_value(self):
        from source_fields import field_extract
        source = dict(url='https://nmct.edu.mn/olympiad',
            text='Зохиомол олимпиад\nБүртгэлийн хураамж\n54,321 ₮\nОлимпиадын өдөр\n4-р сарын 25')
        chosen, excerpt = field_extract('Олимпиадын бүртгэлийн хураамж хэд вэ?', [source])
        self.assertIs(chosen, source)
        self.assertEqual(excerpt, 'Бүртгэлийн хураамж\n54,321 ₮')
        wrong = dict(source, url='https://nmct.edu.mn/elselt')
        self.assertIsNone(field_extract('Олимпиадын бүртгэлийн хураамж хэд вэ?', [wrong]))

    def test_literal_pdf_clause_keeps_eligibility_condition(self):
        from source_fields import field_extract
        source = dict(url='https://nmct.edu.mn/olympiad/test.pdf', text_scope='document_visual_excerpt',
            text='Тус олимпиад нь 2026 оны 9-р ангийн сурагчдад нээлттэй бөгөөд бүртгэлийн хураамж 54321 төгрөг.\nБүртгэл дуусах огноо 4-р сарын 23.')
        chosen, excerpt = field_extract('2026 оны Олимпиадын бүртгэлийн хураамж хэд вэ?', [source])
        self.assertIs(chosen, source)
        self.assertEqual(excerpt, source['text'].split('\n')[0])

    def test_amount_lookup_does_not_substitute_for_other_fee_questions(self):
        from source_fields import field_extract
        source = dict(url='https://nmct.edu.mn/olympiad',
            text='Бүртгэлийн хураамж\n54,321 ₮\nОлимпиадын өдөр\n4-р сарын 25')
        for query in ('Олимпиадын бүртгэлийн хураамжийн хугацаа хэд вэ?',
                      'Олимпиадын бүртгэлийн хураамж сар бүр хэд вэ?',
                      'Олимпиадын бүртгэлийн хураамж төлөхгүй бол хэд вэ?'):
            with self.subTest(query=query):
                self.assertIsNone(field_extract(query,[source]))
