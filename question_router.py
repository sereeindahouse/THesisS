"""Bounded, deterministic development routing over the existing content store.

A=fact-backed stored response, B=stored FAQ, D=clarification, E=refusal within
this imported package. C is disabled. These are proposed development routes,
not human gold. Matching uses canonical questions, explicit aliases, and a
fully consumed admission-choice grammar bound to an existing fact family.
Neither a retrieval score nor a clarification establishes answer support.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from time import perf_counter

from retrieval_probe import terms
from sqlite_retrieval import ReadOnlyContentStore, exact_key, search_content

ROOT = Path(__file__).resolve().parent
POLICY_VERSION = 'bounded-exact-choice-v2'

# The existing question audit proposes these fact routes. A returns the same
# reviewed-format stored response and its fact dependencies, not a new template.
# Unknown/new FAQ IDs default to B. This is not an inferred/gold route label.
FACT_RESPONSE_FAQS = frozenset({'faq.contact', 'faq.arc.courses'})
YEAR_REQUIRED_FAQS = frozenset({'faq.arc.courses'})
ENTITY_TERMS = {'faq.sakura': frozenset({'sakura'}),
                'faq.arc.courses': frozenset({'arc'})}

# Generic question words cannot justify suggesting an unrelated school FAQ.
# These exact tokens are a transparent development rule, not Mongolian stemming.
QUESTION_WORDS = frozenset('''сургуулийн сургууль сургуулиас танай манай би миний
энэ тэр нь юм уу юу вэ бэ яаж ямар хэд хэдэн хэзээ хаана хаанаас хэрхэн тухай
талаар мэдээлэл мэдээллийг мэдээллийн мэдээллээ хэлнэ хэлж хэлээч хэлээд өгнө
өгч өгөөч өгнөө үү байна байгаа болох болохгүй болохыг бол болохоор гэсэн
тул болон бас эсвэл оны онд он одоо надад please tell me what when where how
the a an is are test тестийн'''.split())
YEAR_RE = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
NUMBER_RE = re.compile(r'\d+')
OFFICE_WORDS = frozenset({'алба', 'албаны', 'албанд', 'албанаас', 'албатай',
                         'албыг', 'албад', 'албандаа', 'албадаа', 'албууд', 'албуудаас'})
YEAR_PREFIX_RE = re.compile(r'^((?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?)\s+'
                            r'(?:оны|онд|хичээлийн жилийн)\s+(.+)$', re.IGNORECASE)
YEAR_RANGE_RE = re.compile(r'(?<!\d)((?:19|20)\d{2})\s*[–—-]\s*((?:19|20)\d{2})(?!\d)')


def _admission_choice_request(query):
    """Recognize a complete yes/no request, never discard an unknown clause.

    This maps question meaning to an existing fact family; it does not supply
    the policy, its year, or an answer. Those remain in the pinned package.
    """
    value = exact_key(query)
    year = YEAR_PREFIX_RE.fullmatch(value)
    scope, body = (year.group(1), year.group(2)) if year else (None, value)
    prefix = (r'(?:элсэлтэд|элсэлтийн\s+(?:цахим\s+)?бүртгэл(?:д|ийн\s+үед))\s+')
    one = (r'(?:ганцхан|ганц|нэгхэн|нэг)\s+мэргэж(?:ил|лийн\s+хөтөлбөр)\s+'
           r'(?:сонгоод|сонгож|сонгон)\s+(?:бүртгүүлж\s+)?болох\s+уу')
    second = (r'(?:мэргэжлийн\s+)?(?:2\s*[-–]?\s*р|хоёр\s+дахь|хоёрдугаар)\s+'
              r'(?:мэргэжлийн\s+)?сонголт(?:ыг)?\s+'
              r'(?:заавал\s+хийх\s+(?:ёстой\s+)?(?:юу|үү)|'
              r'хийхгүй\s+байж\s+болох\s+уу|орхиж\s+болох\s+уу)')
    return dict(year_scope=scope) if re.fullmatch(prefix + '(?:' + one + '|' + second + ')', body) else None


def _fact_year_scope(fact):
    """Read positive structured coverage; prose may mention excluded years."""
    value = fact.get('value')
    scope = value.get('year_scope') if isinstance(value, dict) else None
    if not isinstance(scope, str) or not re.fullmatch(
            r'(?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?', scope):
        return None
    return re.sub(r'\s*[–—-]\s*', '–', scope)


def _tuition_calendar_request(query):
    value=exact_key(query)
    amount=r'(?:яг\s+)?хэд\s+(?:(?:болох|байх|байсан|байдаг)\s+)?(?:вэ|бэ)'
    year = YEAR_PREFIX_RE.fullmatch(value)
    if (year and len(YEAR_RE.findall(year.group(1))) == 1
            and re.fullmatch(r'сургалтын\s+төлбөр\s+'+amount,year.group(2))):
        return year.group(1)
    trailing=re.fullmatch(r'сургалтын\s+төлбөр\s+((?:19|20)\d{2})\s+он(?:д|ы)\s+'+amount,value)
    return trailing[1] if trailing else None


def _live_class_clock_request(query):
    # A narrow complete question about a live class start is not answered from
    # historical admission exam durations or general contact opening hours.
    value = exact_key(query)
    return bool(re.fullmatch(r'(?:манай\s+)?(?:[1-9]\s*[-–]?\s*р\s+курси(?:йн|йнхний)\s+)?'
        r'хичээл\s+маргааш\s+хэдэн\s+цагт\s+(?:эхлэх|эхэлдэг|орох|ордог)\s+(?:вэ|бэ)', value))


def _topic_words(text):
    return set(terms(text)) - QUESTION_WORDS - set(NUMBER_RE.findall(text))


def _support_text(faq, facts):
    return ' '.join([faq['answer'], faq['scope'], *[
        json.dumps(facts[fid]['value'], ensure_ascii=False) + ' ' + facts[fid]['scope']
        for fid in faq['fact_ids']]])


def _guard_codes(preview, allow_draft):
    reasons = preview.get('answer_blocked_reasons', preview['blocked_reasons'])
    codes = []
    if any('approval_status=draft' in reason for reason in reasons):
        codes.append('approval_required')
    if any('approval_status=' in reason and 'approval_status=draft' not in reason
           for reason in reasons):
        codes.append('content_rejected_or_unapproved')
    if any('expired for' in reason for reason in reasons):
        codes.append('expired_content')
    if any('not yet valid' in reason for reason in reasons):
        codes.append('future_validity')
    if preview.get('answer_status') != 'complete_in_scope':
        codes.append('partial_answer')
    if not allow_draft and preview['unknown_validity_records']:
        codes.append('unknown_validity')
    return codes or ['answer_guard_blocked']


def personal_identifier_request(query):
    """Recognise a person's identifier lookup, not organisation IDs or form help.

    A published teacher contact card cannot answer a register/passport request.
    The institutional information scope does not expose those personal fields.
    No identifier values, names or guessed identity are stored in this rule.
    """
    if not isinstance(query,str):
        return False
    q=query.casefold()
    person=(r'(?:багш(?:ийн|ын)?|эрхлэгч(?:ийн)?|захир(?:ал|лын)|ажилт(?:ан|ны)|'
            r'оюут(?:ан|ны)|суралцагч(?:ийн)?|түүний|миний|өөрийн|'
            r'(?<!\w)[а-яөүё]\.\s*[а-яөүё]{2,40})')
    identifier=(r'(?:регистр(?:ийн|ын)?|паспорт(?:ын)?|иргэний\s+үнэмлэх(?:ийн)?|'
                r'иргэний\s+бүртгэл(?:ийн)?)\s*(?:дугаар(?:ыг|ийг|аа)?|№)')
    explicit_lookup=r'хэд|харуул|өг(?:нө|өөч|ч|өх)|хэл(?:нэ|ээч|ж|ээд)?(?!\w)'
    for clause in re.split(r'[!?;,\n]|(?<=[а-яөүё]{2})\.\s+',q):
        if not re.search(explicit_lookup+r'|ямар|аль',clause):
            continue
        if (re.search(r'формат|хэрхэн|яаж|хаана\s+(?:бич|оруул)',clause)
                and not re.search(explicit_lookup,clause)):
            continue
        pattern=person+r'(?P<bridge>(?:\s+[а-яөүё.\-]+){0,2})\s+'+identifier
        for match in re.finditer(pattern,clause):
            if re.search(r'сургуул|компани|байгууллаг|коллеж|тэнхим',match['bridge']):
                continue
            return True
    return False


def personal_record_request(query):
    """Recognise a private student-record lookup, not public policy or help.

    A person/possessive, a record field and a request to retrieve that record
    must occur together. General requirements, instructions for checking one's
    own portal and supplied-value conditional questions remain ordinary school
    questions. This is a bounded wording guard, not identity or account access.
    """
    if not isinstance(query, str):
        return False
    owner = (r'(?<!\w)(?:миний|минийх|надад|би|бидний|өөрийн|түүний|'
             r'оюутны|сурагчийн|суралцагчийн)(?!\w)|'
             r'(?<!\w)манай\s+(?:ангийн|бүлгийн|курсын)(?!\w)|'
             r'(?<!\w)[а-яөүё]\.\s*[а-яөүё]{2,40}')
    academic = (r'(?<!\w)(?:голч(?:оо|ийн|ийг)?(?:\s+дүн(?:г|гээ|гийн)?)?|'
                r'дүн(?:г|гээ|гийн(?:\s+хуудас)?)?|ирц(?:ээ|ийн|ийг)?)(?!\w)')
    payment = (r'(?<!\w)(?:төлбөр(?:өө|ийн|ийг|ийнхээ)?|хураамж(?:аа|ийн|ийг)?|'
               r'мөнгө(?:өө|ний|ийг)?|гүйлгээ(?:ний|гээ|г)?|данс(?:ны|аа)?)(?!\w)')
    record_state = (r'үлдэгд(?:эл|лээ|лийг|лийн)|түүх|төлсөн|төлөөгүй|төлөгдсөн|'
                    r'орсон|шилжсэн|өр(?:тэй|ийг|ийн)?(?!\w)|баримт|баталгаажсан')
    possessive = (r'(?<!\w)(?:голчоо|дүнгээ|ирцээ|төлбөрөө|хураамжаа|мөнгөө|'
                  r'үлдэгдлээ|гүйлгээгээ)(?!\w)|'
                  r'(?<!\w)(?:минь|маань)(?!\w)')
    lookup = (r'(?<!\w)(?:хэд(?:эн)?|ямар|аль|харуул\w*|үзүүл\w*|шалг\w*|'
              r'хэл\w*|өг(?:нө|өөч|ч|өх)|гарга\w*|илгээ\w*|мэдмээр|мэдэх)(?!\w)')
    help_or_policy = (r'(?<!\w)(?:яаж|хэрхэн|хаана(?:ас)?|яагаад|шаардлага\w*|шаарддаг|'
                      r'тооцдог|тооцоолдог|тооцох|тооцоолох)(?!\w)|'
                      r'байх\s+ёстой|юу\s+гэсэн\s+үг|ямар\s+(?:систем|цэс|хэсэг)')
    direct_lookup = (r'харуул\w*|үзүүл\w*|(?:шалг\w*|хэл\w*|гарга\w*)\s+'
                     r'(?:(?:надад|нь|даа)\s+)?өг(?:өөч|нө|ч|өх)|'
                     r'(?<!\w)хэд\s+(?:гарсан|байгааг|гарсныг)(?!\w)')
    for clause in re.split(r'[!?;\n]|\.(?=\s+(?:миний|би|надад|харин|мөн|түүний)\b)',
                           query.casefold()):
        field = re.search(academic, clause)
        financial_record = bool(re.search(payment, clause) and re.search(record_state, clause))
        if not (field or financial_record):
            continue
        if not (re.search(owner, clause) or re.search(possessive, clause)):
            continue
        if financial_record and not field:
            # A supplied payment is an input to an admission-policy question,
            # not a request to discover whether that payment is in an account.
            # Keep an additional explicit account lookup in the same clause.
            premise = re.search(payment + r'\s+(?:төлсөн|төлөгдсөн|шилжүүлсэн)\s+'
                                r'(?:бол|байвал)(?!\w)', clause)
            outcome = re.search(r'оюутан\s+бол\w*|суралцах\s+эрх\w*|'
                                r'элсэх\s+эрх\w*|элсэн\s+суралцах', clause)
            if premise and outcome:
                remainder = clause[:premise.start()] + ' ' + clause[premise.end():]
                other_account_request = (re.search(payment, remainder)
                    and re.search(record_state, remainder)
                    and re.search(lookup + r'|(?<!\w)(?:уу|үү|юу|эсэх)(?!\w)', remainder))
                if not other_account_request:
                    continue
        if re.search(r'(?:харуул|үзүүл|шалг|хэл|гарга|илгээ)\w*\s+'
                     r'(?:хэрэггүй|шаардлагагүй)(?!\w)|'
                     r'(?<!\w)(?:битгий|бүү)\s+(?:харуул|үзүүл|шалг|хэл|гарга|илгээ)', clause):
            continue
        # A supplied GPA/attendance is an input to a policy question, not a
        # request to discover a hidden recorded value. A separate preceding
        # lookup clause is still handled independently by this loop.
        if field:
            following = clause[field.end():]
            if re.match(r'\s+(?:биш|асуугаагүй|хүсээгүй)(?!\w)', following):
                continue
            supplied = re.match(r'\s*(?:маань\s+|минь\s+)?\d+(?:[.,]\d+)?\s*%?'
                                r'\s*(?:байвал|бол|болбол|хүрвэл|тохиолдолд|'
                                r'(?:байсан|байгаа)\s+бол|гэж\s+үзвэл)(?!\w)', following)
            if supplied:
                continue
        if re.search(help_or_policy, clause) and not re.search(direct_lookup, clause):
            continue
        # A yes/no question about a recorded payment is also an account lookup.
        payment_check = financial_record and bool(re.search(r'(?<!\w)(?:уу|үү|юу|эсэх)(?!\w)', clause))
        if re.search(lookup, clause) or payment_check:
            return True
    return False


def personal_record_service_request(query):
    """Identify help accessing one's records without claiming a record lookup.

    The application has no student-account/portal integration. This capability
    boundary is separate from published grading methods, eligibility policies,
    admission-result announcements and a supplied GPA used in a condition.
    """
    if not isinstance(query, str):
        return False
    for clause in re.split(r'[!?;\n]', query.casefold()):
        if not re.search(r'(?<!\w)(?:яаж|хэрхэн|хаана(?:ас)?)(?!\w)', clause):
            continue
        if re.search(r'тооц|шаардлага|шаарддаг|байх\s+ёстой', clause):
            continue
        owner = re.search(r'(?<!\w)(?:миний|өөрийн|надад)(?!\w)|'
                          r'(?<!\w)(?:голчоо|дүнгээ|ирцээ|төлбөрөө|үлдэгдлээ)(?!\w)', clause)
        academic = re.search(r'(?<!\w)(?:голч(?:оо|ийн|ийг)?|дүн(?:г|гээ|гийн)?|'
                             r'ирц(?:ээ|ийн|ийг)?)(?!\w)', clause)
        payment = bool(re.search(r'төлбөр|гүйлгээ|хураамж', clause)
                       and re.search(r'үлдэгд|төлсөн|орсон|түүх|баримт|эсэх', clause))
        access = re.search(r'хар(?:ах|ж|даг|на)|үз(?:эх|эж|дэг|нэ)|шалг(?:ах|аж|адаг|ана)|'
                           r'нэвтр|ав(?:ах|ч|даг|на)', clause)
        if owner and (academic or payment) and access:
            if re.search(r'\d+(?:[.,]\d+)?\s*(?:байвал|бол|болбол|хүрвэл)(?!\w)', clause):
                continue
            return True
    return False


def _requested_year_value(query):
    """A requested output year is distinct from a missing input year scope."""
    if re.search(r'(?<!\w)(?:аль|ямар|хэдэн)\s+(?:хичээлийн\s+жил(?:ийн|д)?|'
                 r'он(?:ы|д|оос)?)(?!\w)',query,re.I):
        return True
    # An explicit requested-field list can omit "аль": "Хичээлийн жил,
    # улирал ... хэлнэ үү" still asks the system to FIND those values. Keep
    # the list and request predicate in the same clause; a mention of missing
    # year/term metadata alone does not authorize this handoff.
    for clause in re.split(r'[.!?;]',query.casefold()):
        if re.search(r'хэрэггүй|асуугаагүй|шаардлагагүй|хамаагүй',clause):
            continue
        if (re.search(r'(?<!\w)хичээлийн\s+жил(?:ийг)?\s*(?:,|болон|ба)\s*улирал(?:ыг)?(?!\w)',clause)
                and re.search(r'(?<!\w)(?:хэл(?:нэ|ж|ээд|ээрэй)|өг(?:нө|өөч)|'
                              r'нэрл(?:э|энэ|ээрэй)|дурд(?:на|аач)|мэдмээр)(?!\w)',clause)):
            return True
    return False


def route_question(db_path, query, *, allow_draft=False, package_id=None, as_of=None):
    """Route without changing DB, generating text, training or downloading.

    Uses a package pinned by read-only retrieval. Reopening that immutable
    package for policy metadata avoids mixing content from separate imports.
    ``allow_draft`` permits clearly labeled stored development previews with
    unknown dates, matching sqlite_retrieval; known expiry/partial still block.
    Invalid inputs/missing or incompatible stores raise existing CLI/API errors.
    """
    started = perf_counter()
    retrieval = search_content(db_path, query, backend='bm25', top_k=50,
        allow_draft=allow_draft, package_id=package_id, as_of=as_of)
    query = retrieval['query']
    with ReadOnlyContentStore(db_path) as store:
        content = store.export(retrieval['package_id'])
    faqs = {faq['faq_id']: faq for faq in content['faqs']}
    facts = {fact['fact_id']: fact for fact in content['facts']}
    literal_exact_ids = retrieval['exact_matches']
    year_prefix = YEAR_PREFIX_RE.fullmatch(query)
    binding_id = None
    # A literal alias is an intent spelling, not evidence for its stated year.
    # Explicit academic years must still match the positive fact year_scope;
    # a caution such as "2044 оны журам биш" never expands that scope.
    choice_request = _admission_choice_request(query) if not literal_exact_ids or YEAR_RE.search(query) else None
    choice_facts = {fid: fact for fid, fact in facts.items()
                    if fact.get('entity_id') == 'nmct.admissions'
                    and re.fullmatch(r'second_choice(?:\.[a-zA-Z0-9_]+)?', fact.get('key', ''))
                    and _fact_year_scope(fact)}
    choice_ids = []
    if choice_request and choice_request['year_scope']:
        requested_scope = re.sub(r'\s*[–—-]\s*', '–', choice_request['year_scope'])
        choice_ids = [faq_id for faq_id, faq in faqs.items()
                      if len(faq['fact_ids']) == 1 and faq['fact_ids'][0] in choice_facts
                      and _fact_year_scope(choice_facts[faq['fact_ids'][0]]) == requested_scope]
        if len(choice_ids) == 1:
            binding_id = choice_ids[0]
            retrieval = search_content(db_path, faqs[binding_id]['question'], backend='bm25', top_k=50,
                allow_draft=allow_draft, package_id=retrieval['package_id'],
                as_of=date.fromisoformat(retrieval['as_of']))
    if not literal_exact_ids and year_prefix and not binding_id:
        # Only this anchored, explicit year grammar is supported. It is a
        # supplied constraint on a literal stored base question, not an alias,
        # fuzzy intent, STT correction or authorization to discard other words.
        base = year_prefix.group(2)
        ids = [faq_id for faq_id, faq in faqs.items() if faq_id in YEAR_REQUIRED_FAQS
               and exact_key(base) in {exact_key(text) for text in
                   [faq['question'], *faq['question_aliases']]}]
        if len(ids) == 1:
            binding_id = ids[0]
            retrieval = search_content(db_path, base, backend='bm25', top_k=50,
                allow_draft=allow_draft, package_id=retrieval['package_id'],
                as_of=date.fromisoformat(retrieval['as_of']))
    query_words = _topic_words(query)
    exact_ids = retrieval['exact_matches']
    # Restrict clarification candidates to content-bearing question wording.
    # Answer-text overlap or common particles alone cannot establish relevance.
    candidates = [candidate for candidate in retrieval['candidates']
        if candidate['faq_id'] in exact_ids or any(query_words & _topic_words(text)
            for text in [faqs[candidate['faq_id']]['question'],
                         *faqs[candidate['faq_id']]['question_aliases']])]
    if exact_ids:
        # Once an exact intent exists, unrelated ranking candidates cannot
        # supply constraints/citations or become competing clarification clicks.
        candidates = [candidate for candidate in candidates if candidate['faq_id'] in exact_ids]
    result = dict(query=query, package_id=retrieval['package_id'],
        mode=retrieval['mode'], as_of=retrieval['as_of'],
        policy_version=POLICY_VERSION, route_definition_status='development_proposed_not_gold',
        route='E', reason_code=None, reason_codes=[], message=None, clarification=None,
        answer=None, answer_faq_id=None, answer_kind=None, intended_answer_route=None,
        citations=[], candidates=candidates, exact_matches=literal_exact_ids,
        binding_faq_id=binding_id,
        match_kind='bounded_admission_choice' if choice_request and binding_id else
                   ('explicit_year_literal_base' if binding_id else
                   ('literal_exact' if exact_ids else 'lexical_candidates')),
        unknown_validity_records=[], human_gold=False, c_enabled=False,
        generated=False, llm_calls=0, score_is_probability=False,
        automatic_approval=False, training_performed=False, database_modified=False,
        scope='Only the imported facts/FAQ package; not a claim about all school information.')
    evidence = {}
    for candidate in candidates:
        for citation in candidate['citations']:
            evidence[(citation['document_id'], citation['version'], citation['locator'])] = citation
    result['citations'] = [evidence[key] for key in sorted(evidence)]

    def finish(route, codes, message, clarification=None):
        result.update(route=route, reason_code=codes[0], reason_codes=codes,
                      message=message, clarification=clarification,
                      latency_ms=round((perf_counter() - started) * 1000, 3))
        return result

    def clarify(kind, message, options, years=()):
        return finish('D', [kind], message, dict(kind=kind, question=message,
            options=[{'faq_id': faq_id, 'question': faqs[faq_id]['question']}
                     for faq_id in options], supported_years=sorted(years)))

    def clarify_year(faq_id):
        if _requested_year_value(query):
            # Preserve the entire question for the web evidence pipeline; do
            # not ask the user to supply the very year they asked us to find.
            result.update(citations=[],candidates=[],clarification=None)
            return finish('E',['requested_year_value_lookup'],
                'Асуусан он, хичээлийн жилийг эхээс хайж тогтооно. '
                'Хадгалсан богино FAQ-аар асуултын бусад талбарыг орлуулахгүй.')
        years = sorted(set(YEAR_RE.findall(support[faq_id])))
        year_label = '–'.join(years)
        value = clarify('missing_year', 'Аль оны эсвэл хичээлийн жилийн мэдээлэл хэрэгтэй вэ?', [], years)
        if year_label:
            value['clarification']['options'] = [dict(faq_id=faq_id,
                question=f'{year_label} оны {faqs[faq_id]["question"]}',
                binding='explicit_year_literal_base', supplied_years=years)]
        return value

    if personal_identifier_request(query):
        result.update(citations=[],candidates=[],exact_matches=[])
        return finish('E',['personal_identifier_outside_scope'],
            'Энэ сургуулийн мэдээллийн систем хүний регистр, паспорт, иргэний үнэмлэхийн дугаар өгөхгүй. '
            'Нийтэлсэн албан утас, имэйлийг асуусан хувийн дугаарын оронд үзүүлэхгүй.')

    if personal_record_request(query):
        result.update(citations=[], candidates=[], exact_matches=[], binding_faq_id=None)
        return finish('E', ['personal_record_outside_scope'],
            'Энэ чат таны болон бусад суралцагчийн хувийн дүн, ирц, төлбөрийн бүртгэлд хандахгүй. '
            'Өөрийн эрхтэй сургалтын систем эсвэл сургалтын албаар мэдээллээ шалгана уу. '
            'Ерөнхий элсэлт, сургалтын шаардлагыг хувийн бүртгэлийн хариу болгон орлуулахгүй.')

    if personal_record_service_request(query):
        result.update(citations=[], candidates=[], exact_matches=[], binding_faq_id=None)
        return finish('E', ['personal_record_service_unavailable'],
            'Та өөрийн дүн, ирц эсвэл төлбөрийн бүртгэлээ хаанаас, хэрхэн харахыг асууж байна. '
            'Энэ чат суралцагчийн хувийн бүртгэлтэй системд холбогдоогүй. '
            'Тухайн системийн нэр, хаяг, нэвтрэх цэсийг баталгаатай зааж өгөх боломжгүй байна.')

    if any(int(start) > int(end) for start, end in YEAR_RANGE_RE.findall(query)):
        return finish('E', ['invalid_year_range'],
            'Асуултын жилийн хүрээ урвуу байна. Оны дарааллыг автоматаар засахгүй.')

    if _live_class_clock_request(query):
        result.update(citations=[], candidates=[])
        return finish('E', ['live_class_schedule_not_available'],
            'Энэ чатад маргаашийн тухайн ангийн хичээлийн хуваарь холбогдоогүй байна. '
            'Тэнхим, бүлгээ заагаад ангийн багш эсвэл сургалтын албанаас эхлэх цагийг тодруулаарай.')

    tuition_year = _tuition_calendar_request(query)
    tuition_facts = [fact for fact in facts.values()
                     if fact.get('entity_id') == 'nmct.admissions'
                     and re.fullmatch(r'annual_tuition(?:\.[a-zA-Z0-9_]+)?', fact.get('key', ''))]
    tuition_scopes = {_fact_year_scope(fact) for fact in tuition_facts} - {None}
    if tuition_year and tuition_scopes and tuition_year not in tuition_scopes:
        result.update(requested_years=[tuition_year], supported_years=sorted(tuition_scopes), citations=[])
        return finish('E', ['tuition_year_scope_not_available'],
            f'{tuition_year} оны сургалтын төлбөрийн дүнг одоогийн хариултын эх батлахгүй байна. '
            'Өөр оны үнийг орлуулахгүй. Хичээлийн жилийг асуусан бол эхлэх, дуусах хоёр оноор нь тодруулна уу.')

    if choice_request and choice_facts and not binding_id:
        years = sorted({_fact_year_scope(fact) for fact in choice_facts.values()})
        result['citations'] = []
        if not choice_request['year_scope']:
            return clarify('admission_choice_year_needed',
                'Аль оны эсвэл хичээлийн жилийн элсэлтийн мэргэжил сонголтын журмыг асууж байна вэ?', [],
                {year for scope in years for year in YEAR_RE.findall(scope)})
        return finish('E', ['admission_choice_scope_not_available'],
            'Асуусан оны хүрээнд мэргэжлийн сонголтыг тайлбарлах нэг тодорхой эхтэй хариулт олдсонгүй. '
            'Өөр оны журмыг орлуулахгүй; элсэлтийн хичээлийн жилийн хүрээг нягтлаарай.')

    if not candidates:
        return finish('E', ['no_supported_question_match'],
            'Одоогийн facts/FAQ багцад энэ асуултыг дэмжих таарсан асуулт алга. '
            'Сайтын бүх мэдээлэлд байхгүй гэж дүгнээгүй; хариулт зохиохгүй.')
    related_ids = [candidate['faq_id'] for candidate in candidates]
    support = {faq_id: _support_text(faqs[faq_id], facts) for faq_id in related_ids}
    query_years = set(YEAR_RE.findall(query))
    constraint_ids = exact_ids if len(exact_ids) == 1 else related_ids
    supported_years = {year for faq_id in constraint_ids for year in YEAR_RE.findall(support[faq_id])}
    year_compatible = [faq_id for faq_id in constraint_ids
                       if query_years <= set(YEAR_RE.findall(support[faq_id]))]
    if query_years and not year_compatible:
        result['requested_years'] = sorted(query_years)
        result['supported_years'] = sorted(supported_years)
        return finish('E', ['unsupported_year'],
            'Асуусан оныг дэмжих facts/FAQ энэ багцад алга. Өөр оны мэдээллийг орлуулахгүй.')
    query_numbers = set(NUMBER_RE.findall(query)) - query_years
    number_compatible = [faq_id for faq_id in constraint_ids
                         if query_numbers <= set(NUMBER_RE.findall(support[faq_id]))]
    if query_numbers and not number_compatible:
        return finish('E', ['unmatched_numeric_constraints'],
            'Асуултад байгаа тоо эсвэл дугаарыг энэ багцын эхээр батлах боломжгүй. Тоог засаж таахгүй.')

    # These exclusions express the actual five-FAQ scope, not broad semantic
    # classification. General contact never substitutes for an office-specific
    # number; historical Sakura activities never establish live enrollment.
    tokens = set(terms(query))
    known_entities = set().union(*ENTITY_TERMS.values())
    requested_entities = tokens & known_entities
    if len(exact_ids) == 1 and requested_entities:
        faq_id = exact_ids[0]
        canonical_entities = (set(terms(faqs[faq_id]['question'])) | set(terms(support[faq_id]))) & known_entities
        if not requested_entities <= canonical_entities:
            return finish('E', ['unmatched_named_entity'],
                'Асуултын нэр нь яг таарсан FAQ-ийн өөрийн эх, хүрээтэй зөрж байна. Нэрийг орлуулахгүй.')
    office_requested = bool(tokens & OFFICE_WORDS)
    office_options = [faq_id for faq_id in related_ids if faq_id != 'faq.contact' and any(
        word in OFFICE_WORDS for text in [faqs[faq_id]['question'], *faqs[faq_id]['question_aliases']]
        for word in terms(text))]
    if ('faq.contact' in related_ids and office_requested
            and (exact_ids == ['faq.contact'] or not office_options)):
        return finish('E', ['specific_scope_not_supported'],
            'Энэ багцад сургуулийн ерөнхий холбоо бий; албаны тусгай холбоо батлагдаагүй.')
    if 'faq.sakura' in related_ids and tokens & {'нээлттэй', 'бүртгэл', 'бүртгэлийн', 'одоо'}:
        return finish('E', ['live_status_not_supported'],
            'Sakura-ийн түүхэн танилцуулга нь өнөөдрийн бүртгэл, боломжийн төлөвийг батлахгүй.')

    preview = retrieval['exact_match_preview']
    if len(exact_ids) == 1:
        faq_id = exact_ids[0]
        result['intended_answer_route'] = ('A' if faq_id in FACT_RESPONSE_FAQS
                                            and faqs[faq_id]['fact_ids'] else 'B')
        result['unknown_validity_records'] = preview['unknown_validity_records']
        # Never bypass source/fact/FAQ guards just because clarification is easy.
        if not preview['answer_eligible']:
            return finish('E', _guard_codes(preview, allow_draft),
                'Яг таарсан асуулт байна. Гэхдээ эх, fact, FAQ-ийн баталгаа, '
                'хүчинтэй хугацаа эсвэл хариултын бүрэн байдлын шалгалт хангаагүй.')
        if faq_id in YEAR_REQUIRED_FAQS and not query_years:
            return clarify_year(faq_id)
        result.update(answer=retrieval['answer'], answer_faq_id=faq_id,
            answer_kind=('approved_stored_answer' if preview['approval_status'] == 'approved'
                         and not preview['unknown_validity_records']
                         and all(c['approval_status'] == 'approved' for c in preview['citations'])
                         and not any(facts[fid]['approval_status'] != 'approved' for fid in faqs[faq_id]['fact_ids'])
                         else 'development_draft_preview'),
            fact_ids=faqs[faq_id]['fact_ids'], citations=preview['citations'])
        return finish(result['intended_answer_route'],
            ['exact_stored_draft_preview' if result['answer_kind'] == 'development_draft_preview'
             else 'exact_approved_stored_answer'],
            'Хөгжүүлэлтийн draft хариулт; сургуулиар баталгаажсан хариулт биш.'
            if result['answer_kind'] == 'development_draft_preview'
            else 'Яг таарсан, эхтэй бөгөөд хүчинтэй хугацаа нь тодорхой хадгалсан хариулт.')
    if len(exact_ids) > 1:
        if query_years or query_numbers or requested_entities or office_requested:
            return clarify('ambiguous_constrained_exact_match',
                'Ижил хэлбэр хэд хэдэн FAQ-д байна. Нэр, он, тоо эсвэл албаны хүрээг хасаж сонголт өгөхгүй; эх ба хүрээг нягтлах шаардлагатай.',
                [], query_years)
        return clarify('ambiguous_exact_match',
            'Ижил асуултын хэлбэр хэд хэдэн FAQ-д байна. Аль асуултыг хэлж байна вэ?', exact_ids)

    # Unsupported named entities are never silently changed into known ones.
    latin_query = set(re.findall(r'[a-z][a-z0-9]*', exact_key(query))) - QUESTION_WORDS
    latin_supported = {token for faq_id in related_ids
        for text in [faqs[faq_id]['question'], *faqs[faq_id]['question_aliases']]
        for token in re.findall(r'[a-z][a-z0-9]*', exact_key(text))}
    if latin_query - latin_supported:
        return finish('E', ['unmatched_named_entity'],
            'Асуултын нэрийг энэ багцын хадгалсан асуулттай баттай холбож чадсангүй. Нэрийг орлуулахгүй.')
    compatible_ids = [faq_id for faq_id in related_ids
        if (not query_years or faq_id in year_compatible)
        and (not query_numbers or faq_id in number_compatible)
        and (not office_requested or faq_id in office_options)
        and (not requested_entities or requested_entities <= ENTITY_TERMS.get(faq_id, frozenset()))]
    if not compatible_ids:
        return finish('E', ['constraints_not_supported_together'],
            'Асуултын нэр, он, тоо эсвэл хүрээг хамтад нь дэмжих нэг хадгалсан асуулт алга. Тааж нэгтгэхгүй.')
    related_ids = compatible_ids
    result['candidates'] = [c for c in candidates if c['faq_id'] in related_ids]
    evidence = {}
    for candidate in result['candidates']:
        for citation in candidate['citations']:
            evidence[(citation['document_id'], citation['version'], citation['locator'])] = citation
    result['citations'] = [evidence[key] for key in sorted(evidence)]
    if query_years or query_numbers or office_requested:
        # Replacing a constrained user request with a shorter canonical option
        # would silently drop its year/number/entity. Keep the original request
        # visible and ask for scope review instead of offering that unsafe click.
        return clarify('constrained_wording_not_exact',
            'Асуусан нэр, он, тоонд тохирох мэдээллийг одоогоор баттай ялгаж чадсангүй. '
            'Яг аль хүний, хөтөлбөрийн эсвэл хичээлийн жилийн ямар мэдээлэл хэрэгтэйг нэг өгүүлбэрээр тодруулна уу.', [], query_years)
    entity_options = {faq_id: ENTITY_TERMS[faq_id] for faq_id in related_ids if faq_id in ENTITY_TERMS}
    if len(entity_options) > 1 and not any(tokens & values for values in entity_options.values()):
        return clarify('missing_entity', 'Аль хамтын ажиллагааны тухай асууж байна вэ?', entity_options)
    if len(related_ids) == 1 and related_ids[0] in YEAR_REQUIRED_FAQS and not query_years:
        return clarify_year(related_ids[0])
    # Scores do not choose an answer. A user's next request must independently
    # pass exact wording, scope/year and approval/validity checks.
    return clarify('select_supported_question',
        'Төстэй асуулт олдлоо. Хариулахын өмнө аль хадгалсан асуултыг хэлж байгааг тодруулъя.', related_ids)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Эхтэй exact/D/E development router; C/LLM ажиллахгүй.')
    parser.add_argument('query')
    parser.add_argument('--db', type=Path, default=ROOT / 'runtime/content.db')
    parser.add_argument('--package-id')
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--allow-draft', action='store_true')
    args = parser.parse_args()
    try:
        result = route_question(args.db, args.query, allow_draft=args.allow_draft,
                                package_id=args.package_id, as_of=args.as_of)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
