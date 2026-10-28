"""Literal event-role guards for dated school history, not semantic entailment.

Years and counts always come from selected evidence. A school founding year
cannot fill a programme-opening year or the year of the first graduation.
"""
import re

_YEAR = r'(?<!\d)(?:19|20)\d{2}(?!\d)'
_NEGATIVE = r'магадгүй|төлөвлө|тодорхойгүй|үгүйсгэ|нээгдээгүй|нээхгүй|төгсөөгүй|төгсөхгүй|батлагдаагүй|аваагүй|хэрэв|авбал|\bбиш\b'
_GRADUATED = r'төгс(?:өв|сөн|өж)\b|гардан\s+ав(?:ч(?:ээ)?|сан|жээ|лаа|ав)?\b'
_ELLIPTICAL_COHORT_QUERY = (r'нийт\s+хэдэн\s+удаа\s*[,;]\s*'
    r'хэдэн\s+(?:оюутан|төгсөгч|хүн)\w*\s+төгс\w*')
_CUMULATIVE_QUERY = (r'нийт\s+хэдэн\s+удаа(?:гийн)?\s+төгсөлт|'
    + _ELLIPTICAL_COHORT_QUERY + r'|'
    r'(?:түүнээс|тэр\s+үеэс|анх\s+төгссөнөөс)\s+хойш|'
    r'одоог\s+хүртэл|нийт\s+төгсөгч\w*|'
    r'нийт\s+хэдэн\s+(?:оюутан|хүн)\w*\s+(?:төгс|мэргэжил\s+эзэмш)')


def _graduation_requirements(query):
    """Keep the first cohort and later cumulative counts in separate roles.

    A later ``нийт хэдэн удаагийн төгсөлтөөр хэдэн оюутан`` clause does
    not ask how many people belonged to the first graduating cohort.
    """
    cumulative = re.search(_CUMULATIVE_QUERY, query)
    first = re.search(r'анх\w*(?:\s+\w+){0,3}\s+төгс', query)
    first_query = query[first.start():] if first else ''
    if first and cumulative and cumulative.start() > first.start():
        first_query = query[first.start():cumulative.start()]
    result = []
    if first and re.search(r'хэдэн\s+онд|хэзээ', first_query):
        result.append(dict(name='first_graduation_year', label='анхны төгсөлтийн үйл явдалд хамаарах он',
            type='historical_event', event='first_graduation', facet='year', aliases=[]))
    if first and re.search(r'хэдүүл|хэдэн\s+(?:оюутан|төгсөгч|хүн)|тоо\s+хэд', first_query):
        result.append(dict(name='first_graduation_count', label='анхны төгсөлтийн төгсөгчдийн тоо',
            type='historical_event', event='first_graduation', facet='count', aliases=[]))
    if cumulative:
        total_query = query[cumulative.start():]
        if first and first.start() > cumulative.start():
            total_query = query[cumulative.start():first.start()]
        if (re.search(r'хэдэн\s+удаа(?:гийн)?\s+төгсөлт', total_query)
                or re.search(_ELLIPTICAL_COHORT_QUERY, total_query)):
            result.append(dict(name='cumulative_graduation_cohorts', label='нийт төгсөлтийн удаагийн тоо',
                type='historical_event', event='cumulative_graduation', facet='cohorts', aliases=[]))
        if re.search(r'хэдүүл|хэдэн\s+(?:оюутан|төгсөгч|хүн)|тоо\s+хэд', total_query):
            result.append(dict(name='cumulative_graduation_count', label='нийт мэргэжил эзэмшсэн төгсөгчдийн тоо',
                type='historical_event', event='cumulative_graduation', facet='count', aliases=[]))
    return result


def event_requirements(query):
    q=query.casefold()
    requirements=_graduation_requirements(q)
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
            # A cumulative clause may share a sentence with the first year;
            # its later numbers still cannot fill the first-cohort field.
            first_value=re.split(r'\s+бөгөөд\s+|\s+харин\s+|өнөөгийн\s+байдлаар|нийт\s+\d+\s+удаа',value,1)[0]
            first=re.search(r'анх\w*\s+(?:\d+\s+)?(?:(?:оюут(?:ан|нууд)|хүн)\w*\s+)?төгс',first_value)
            if not first or not re.search(_GRADUATED,first_value):
                continue
            if requirement['facet']=='count':
                if re.search(r'анх\w*\s+\d+\s+(?:төгсөгч|оюутан|хүн)',first_value):return True
            elif heading or re.search(_YEAR+r'\s+онд?\s*$',first_value[:first.start()]):
                return True
        elif requirement['event']=='cumulative_graduation':
            # Each local cumulative clause must contain its own total and
            # completed graduation predicate. Other sentences, staff counts
            # and annual enrolment cannot supply those values.
            for total in re.split(r'\s+бөгөөд\s+|\s+харин\s+',value):
                if re.search(r'эзэмшээгүй|эзэмшихгүй|байгаагүй|няцаа|таамаг',total):continue
                cohorts=re.search(r'нийт\s+[1-9]\d*\s+удаа(?:гийн)?\s+төгсөлт\w*',total)
                completed=re.search(_GRADUATED+r'|мэргэжил\s+эзэмш(?:сэн|ээд|ив|жээ)\b',total)
                if not completed:continue
                if requirement['facet']=='cohorts' and cohorts:return True
                if requirement['facet']=='count':
                    if cohorts and re.search(r'төгсөлт\w*\s+[1-9]\d*\s+(?:оюутан|хүн)\w*\s+(?:төгс\w*|мэргэжил\s+эзэмш\w*)',total):return True
                    if re.search(r'нийт\s+[1-9]\d*\s+(?:оюутан|хүн|төгсөгч)\w*\s+(?:төгс\w*|мэргэжил\s+эзэмш\w*)',total):return True
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
