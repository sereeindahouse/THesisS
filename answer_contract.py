"""Bounded answer contracts; these are not a semantic entailment classifier."""
import re
import unicodedata

MAX_SPEECH_CHARACTERS = 2000


def spoken_text(result):
    """One shared display-to-speech selection, including draft/clarification text."""
    if result.get('answer') is not None:
        prefix = 'Ноорог, сургуулиар баталгаажаагүй. ' if result.get('answer_kind') == 'development_draft_preview' else ''
        return prefix + result['answer']
    text = result.get('message', '')
    if result.get('clarification'):
        text += ' ' + result['clarification']['question']
    return text


def render_claims(claims):
    cited, lines = [], []
    for claim in claims:
        sid = claim['source_id']
        if sid not in cited:
            cited.append(sid)
        lines.append(f"{claim['text']} [{cited.index(sid) + 1}]")
    return '\n\n'.join(lines), cited


def sentences(text):
    # A field label and its numeric value may occupy adjacent HTML lines.
    # Join only explicit fee labels, never arbitrary neighbouring paragraphs.
    text = re.sub(r'(сургалтын төлбөр|бүртгэлийн хураамж|дотуур байрны төлбөр)[: \t]*\n[ \t]*(?=\d)',
                  r'\1: ', text, flags=re.I)
    # Preserve decimal punctuation inside quantities, but separate statements.
    return re.split(r'(?<!\d)[.!?](?:\s+|$)|(?<=\d)[.!?](?=\s|$)|[;\n]', text.casefold())


def interview_attribute(query):
    q = query.casefold()
    if 'ярилцлаг' not in q:
        return None
    if re.search(r'дүн|хариу', q):
        return 'result_time'
    if re.search(r'эхлэх|эхэл|эхлэ|хэзээ', q):
        return 'start_time'
    if re.search(r'босго|тэнцэх|тэнцэхэд|хамгийн бага|доод оноо', q):
        return 'passing_score'
    if re.search(r'минут|хугацаа|үргэлжил|хэр удаан', q):
        return 'duration'
    if re.search(r'эцэг|асран|хамт|хэнтэй', q):
        return 'companion'
    if 'оноо' in q:
        return 'maximum_score'
    return None


ATTRIBUTE_LABELS = {
    'result_time': 'ярилцлагын дүн гарах хугацааг',
    'start_time': 'ярилцлага эхлэх хугацааг',
    'passing_score': 'ярилцлагад тэнцэх босго оноог',
}


def supports_interview_attribute(query, text):
    """A conservative lexical screen for three observed near-domain gaps.

    Availability in a sentence is necessary here, not sufficient for correctness.
    In particular a date cannot establish an exact number of minutes afterwards.
    """
    field, q = interview_attribute(query), query.casefold()
    for sentence in sentences(text):
        if field == 'result_time':
            matched = re.search(r'дүн|хариу', sentence) and re.search(r'зарла|гарна|гарах|байршуул|нийтэл|мэдэгд', sentence)
            if not matched:
                continue
            units = [unit for unit in ('минут', 'цаг') if unit in q]
            if units and not all(re.search(r'\d+\s*' + unit, sentence) for unit in units):
                continue
            if re.search(r'\d|өдөр|маргааш|долоо хоног', sentence):
                return True
        elif field == 'start_time':
            if re.search(r'ярилцлаг', sentence) and re.search(r'эхэл|эхлэ|эхлэх', sentence) and re.search(r'\d|өдөр|маргааш', sentence):
                return True
        elif field == 'passing_score':
            if re.search(r'босго|тэнц|доошгүй', sentence) and 'оноо' in sentence:
                return True
        else:
            return True
    return False


_QUANTITY = re.compile(r'\d+(?:[.,]\d+)*')
_CONTEXT = {
    'period': {'year': r'жил(?:д|ийн|ээр)|жилийн', 'month': r'сар(?:д|ын|аар)|сарын'},
    'fee': {'tuition': r'сургалтын\s+төлбөр', 'registration': r'бүртгэлийн\s+(?:хураамж|төлбөр)',
            'dormitory': r'(?:дотуур\s+)?байрны\s+төлбөр'},
    'unit': {'minute': r'минут', 'hour': r'цаг', 'point': r'оноо',
             'currency': r'төгрөг|₮|\bmnt\b'},
}


def _contexts(sentence):
    return {kind: {name for name, pattern in variants.items() if re.search(pattern, sentence)}
            for kind, variants in _CONTEXT.items()}


def quantity_context_supported(statement, quote):
    """Reject explicit number/unit/fee-scope changes in short clauses.

    This intentionally does not certify negation, causal claims, all synonyms,
    or bindings between several quantities in the same sentence.
    """
    source_sentences = sentences(quote)
    for sentence in sentences(statement):
        context = _contexts(sentence)
        for number in _QUANTITY.findall(sentence):
            matches = [part for part in source_sentences if number in _QUANTITY.findall(part)]
            if not any(all(not labels or labels <= _contexts(part)[kind]
                           for kind, labels in context.items()) for part in matches):
                return False
    return True


def tuition_amount_query(query):
    text = unicodedata.normalize('NFC', query).casefold()
    if not re.search(r'\bсургалтын\s+төлбөр(?:ийн|ийг)?\b', text):
        return False
    # Keep this vocabulary explicit: programmes, discounts, refund policy,
    # instalments, special student groups and live status require other evidence.
    words = set(re.findall(r'[^\W\d_]+', text))
    allowed = set('сургалтын төлбөр төлбөрийн төлбөрийг хэд хэдэн төгрөг төгрөгөөр ₮ mnt '
                  'жил жилийн жилд жилээр нэг сард сарын сараар сар бүр '
                  'оны онд он хичээлийн үү уу вэ бэ юм байна мөн зөв эсэхийг '
                  'энэ тэр танай сургуулийн хэлээд өгөөч'.split())
    return words <= allowed


def tuition_period_notice(query, excerpt):
    if (tuition_amount_query(query) and re.search(r'\b(?:сард|сарын|сараар|сар)\b', query.casefold())
            and re.search(r'жилд|жилийн', excerpt.casefold())):
        return ('Энэ заалтад сургалтын төлбөрийг жилээр заасан. '
                'Сарын төлбөрийн дүн, хуваарийг энд тодорхойлоогүй.')
    return ''
