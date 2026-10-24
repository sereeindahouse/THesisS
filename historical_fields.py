"""Literal event-role guards for dated school history, not semantic entailment.

Years and counts always come from selected evidence. A school founding year
cannot fill a programme-opening year or the year of the first graduation.
"""
import re

_YEAR = r'(?<!\d)(?:19|20)\d{2}(?!\d)'
_NEGATIVE = r'магадгүй|төлөвлө|тодорхойгүй|үгүйсгэ|нээгдээгүй|нээхгүй|төгсөөгүй|төгсөхгүй|батлагдаагүй|аваагүй|хэрэв|авбал|\bбиш\b'


def event_requirements(query):
    q=query.casefold()
    requirements=[]
    graduation=bool(re.search(r'анх\w*(?:\s+\w+){0,3}\s+төгс',q))
    if graduation and re.search(r'хэдэн\s+онд|хэзээ',q):
        requirements.append(dict(name='first_graduation_year',label='анхны төгсөлтийн үйл явдалд хамаарах он',
            type='historical_event',event='first_graduation',facet='year',aliases=[]))
    if graduation and re.search(r'хэдүүл|хэдэн\s+(?:оюутан|төгсөгч|хүн)|тоо\s+хэд',q):
        requirements.append(dict(name='first_graduation_count',label='анхны төгсөлтийн төгсөгчдийн тоо',
            type='historical_event',event='first_graduation',facet='count',aliases=[]))
    first_intake=bool(re.search(r'анхны\s+элсэгч\w*',q) and re.search(r'авсан|хүлээн\s+ав',q))
    opening=bool(re.search(r'нээ|нээгд|эхлүүл',q))
    if ('хөтөлбөр' in q and (opening or first_intake)
            and (re.search(r'хэдэн\s+онд|хэзээ',q) or re.search(_YEAR,q))):
        # Only literal subject identity is normalized. No school date, programme
        # inventory or fallback department is encoded in these patterns.
        subject=q.split('хөтөлбөр',1)[0]
        generic={'сургуулийн','сургууль','танай','манай','шинэ','монгол','коосэн','энэ','тэр','анх'}
        anchors=[]
        for word in re.findall(r'[^\W\d_]+',subject):
            if word in generic:continue
            for suffix in ('гийн','ийн','ын','ны'):
                if word.endswith(suffix) and len(word)-len(suffix)>=4:
                    word=word[:-len(suffix)];break
            anchors.append(re.escape(word)+r'\w*')
        if anchors:
            event='programme_first_intake' if first_intake else 'programme_opening'
            requirements.append(dict(name=event+'_year',
                label='нэрлэсэн хөтөлбөрийн анхны элсэгчдээ хүлээн авсан он' if first_intake else 'нэрлэсэн хөтөлбөр нээгдсэн он',
                type='historical_event',event=event,facet='year',aliases=[],subject_aliases=anchors))
    return requirements


def _blocks(text):
    """A standalone timeline year owns only the following card, until next year."""
    parts=re.split(r'(?m)^(?=(?:19|20)\d{2}\s*$)',text)
    for part in parts:
        lines=part.strip().splitlines()
        heading=lines[0].strip() if lines and re.fullmatch(_YEAR,lines[0].strip()) else None
        for clause in re.split(r'(?<=[.!?])\s+',part):
            if clause.strip():yield clause,heading


def event_supported(requirement,text):
    for clause,heading in _blocks(text):
        value=clause.casefold()
        if re.search(_NEGATIVE,value):continue
        if requirement['event']=='first_graduation':
            first=re.search(r'анх\w*\s+(?:\d+\s+)?төгс',value)
            if not first or not re.search(r'төгс(?:өв|сөн|өж)\b|гардан\s+ав(?:ч(?:ээ)?|сан|жээ|лаа|ав)?\b',value):
                continue
            if requirement['facet']=='count':
                if re.search(r'анх\w*\s+\d+\s+төгсөгч',value):return True
            elif heading or re.search(_YEAR+r'\s+он\w*.{0,100}анх\w*\s+(?:\d+\s+)?төгс',value):
                return True
        else:
            subject=r'\s+'.join(requirement['subject_aliases'])
            if requirement['event']=='programme_first_intake':
                predicate=(r'хөтөлбөр\w*\s+(?:шинээр\s+нээгд(?:эж|сэн|эв),?\s+)?'
                           r'анхны\s+элсэгч\w*\s+(?:'+_YEAR+r'\s+онд\s+)?'
                           r'(?:хүлээн\s+)?ав(?:сан|ав|ч)\b')
            else:
                predicate=r'хөтөлбөр\w*[^\n.;:!?]{0,60}(?:шинээр\s+)?(?:нээ(?:сэн|в|ж)|нээгд(?:сэн|эв|эж))'
            event=re.search(subject+r'\s+'+predicate,value)
            if not event:continue
            # An undated overview and a different event's year do not suffice.
            if (heading or re.search(_YEAR+r'\s+он\w*\s*$',value[:event.start()])
                    or re.search(_YEAR+r'\s+он\w*',event.group())):return True
    return False


def event_search_query(query):
    requirements=event_requirements(query)
    programmes=[r for r in requirements if r['event'].startswith('programme_')]
    if not programmes:return None
    # Query expansion asks for the same subject's opening event. It supplies no
    # date/value and supplements rather than replacing the original retrieval.
    # Retrieve the relation independently: repeating the subject can bury a
    # timeline under several undated department overviews. The caller accepts
    # an added passage only when event_supported binds the ORIGINAL subject.
    return ('хөтөлбөр анхны элсэгчдээ хүлээн авсан түүх'
            if programmes[0]['event']=='programme_first_intake' else 'хөтөлбөр шинээр нээгдсэн түүх')
