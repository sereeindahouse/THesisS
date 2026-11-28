"""Question understanding before routing: split a compound question, resolve plain names.

The planner never answers and never writes answer text. It only turns one visitor
question into one to three routable questions, then every part goes through the
existing guarded route (reception tables -> stored FAQ -> website sources) on its own.
The composed reply lists each part with its own sourced answer, or says that part was
not found and where to ask. Three closed rules, each switchable in
config/question-planner.json so the thesis can report the planner off and on:

1. split_compound   — "A вэ, B уу?" with a question word on both sides becomes two parts;
                      a part without its own topic (or with the possessive "нь") inherits the
                      subject of the previous part ("…төлбөр хэд вэ, хэсэгчлэн төлж болох уу").
2. class_groups     — "Компьютерын ухааны 2-р курс" -> "КУ-2" when the reception class table
                      has exactly one group for that department and course.
3. staff_names      — "Сэлмаа багш" -> "Б.Сэлмаа багш" when exactly one person in the staff
                      or class table has that given name; only directly before "багш".
4. closed_wording   — the reception table path answers only fixed wordings (a safety design).
                      A class-group question about its room or class teacher is put into that
                      wording ("ХИ-3 анги хэдэн тоот вэ" -> "ХИ-3 анги хаана хичээллэдэг вэ"), and
                      a short office name is replaced by the unique table name it abbreviates
                      ("карьерын төв" -> "Карьер хөгжлийн төв"). Part of class_groups.
                      11/17: also a class teacher's contact ("КУ-2 ангийн багштай яаж холбогдох вэ"
                      -> "КУ-2 ангийн багшийн имэйл"), a class's weekday timetable, and an office's
                      room ("Сургалтын албаны өрөө хаана вэ" -> "Сургалтын алба хаана вэ").
5. teacher_intent   — a named teacher (in the staff table) with a contact, room or meeting
                      question goes to that wording ("Соронзонболд багштай одоо уулзаж болох уу"
                      -> "Н.Соронзонболд багш одоо хичээлтэй юу"). Part of staff_names.

No model, no network; a rule that does not match leaves the text unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

from reception_tables import (MEET_OR_FREE, TIME_LEAD, NUMBER_UNITS, PERSON_NAME, teacher_asked_now, teacher_time_parts, last_vowel, normalize_wording, spoken_form, strip_context_clause,
                              strip_fillers)

CONFIG_PATH = 'config/question-planner.json'
MAX_PARTS = 4
# «юм» alone ends a statement («Багштай уулзах гэсэн юм, имэйл нь юу вэ?» is one request); only
# «юм бэ» asks, and «бэ» is here already (11/17 (5)).
# For a cut inside a sentence without question marks (QuestionPlanner._unpunctuated).
WH_WORD = re.compile(r'юу|хэн\w*|хэд\w*|хаана|хаашаа|хаанаас|хэзээ|ямар|яаж|яах|яагаад|аль')
NO_SECOND_QUESTION = frozenset(('үгүй', 'эсвэл', 'эсхүл', 'гэж', 'гэдэг', 'гэдгийг', 'гэсэн', 'гээд', 'гэвэл', 'гэхээр',
                                'гэхэд', 'та', 'мэдэх', 'мэдэх', 'хэлж', 'хэлээд', 'хэлээч', 'зааж', 'заагаад'))
QUESTION_WORD = re.compile(r'(?<!\w)(?:вэ|бэ|уу|үү|юу|хэн|хэнд|хэнээс|хэд\w*|хаана|хаашаа|хаанаас|хэзээ|'
                           r'ямар|яаж|яах|аль|болох\s+уу|байдаг\s+уу)(?!\w)', re.I)
# «Төлбөр нь хэд вэ?», «Төлбөр нь?»: one noun with «нь» (its) asks about the thing just named, even when
# the noun is a topic word of its own (round 17: after «Дотуур байр байдаг уу?» it was answered with a
# scholarship's «100% / Сургалтын төлбөр …»). The question words are QUESTION_WORD's (review).
OWN_ATTRIBUTE = re.compile(r'\s*[^\W\d_]+\s+нь(?:\s+(?:' + QUESTION_WORD.pattern + r'|хэрхэн)|\s*\?*\s*$)', re.I)
# Words that carry no topic of their own; a part made only of these needs the previous subject.
FUNCTION_WORDS = frozenset('''вэ бэ уу үү юу юм хэн хэнд хэд хэдэн хэдэд хаана хаашаа хэзээ ямар яаж аль
    нь бол болох байдаг байна байх вэ? бас мөн тэгээд мөн ба болон эсвэл гэж гэх юм бэ уу? одоо
    хийж хийх авах өгөх очих төлж төлөх сурч сурах үргэлжлүүлэн хэсэгчлэн'''.split())
GROUP = re.compile(r'(?<![\w-])([А-ЯӨҮЁ]{2}-\d)(?!\d)')
# «хаана» as a word: «хаанаас авах» (where to get a paper) is not where a class meets (review, round 9).
LOCATION = re.compile(r'(?<!\w)хаана(?!\w)|тоот|өрөө|давхар|хичээллэ', re.I)
TIME_WORDS = re.compile(r'өнөөдөр|маргааш|одоо|цаг|гараг|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням', re.I)
OFFICE_QUESTION = re.compile(r'(.{2,60}?)\s+(хаана|хэддүгээр\s+давхарт)(?!\w)(.*)', re.I | re.S)
# A phone question is not rewritten to e-mail: staff phones are never shown, so it goes to the
# phone wording, whose reply says so before offering the school e-mail (no silent field swap).
CONTACT = re.compile(r'холбо(?:о\s+бар|гд)|имэйл|имейл|мэйл|цахим\s+шуудан', re.I)
PHONE = re.compile(r'утас|утс[аы]|phone', re.I)
OTHER_TIME = re.compile(r'маргааш|өчигдөр|нөгөөдөр|(?<!\w)(?:даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)|'
                        r'\d{1,2}:\d{2}|цагт', re.I)
MEETING = re.compile(r'уулз|одоо|чөлөөтэй|(?<!\w)сул(?!\w)|хичээлтэй', re.I)
# The planner's own wording of «who is this person» and the questions its answer already covers.
PERSON_CARD = re.compile(PERSON_NAME + r'(?:\s+багш)?\s+гэж\s+хэн\s+бэ\s*\??', re.I)
PERSON_COVERED = re.compile(PERSON_NAME + r'\s+багш(?:ийн\s+(?:(?:ажлын\s+)?өрөө\s+хаана|и-?мэйл|имэйл|мэйл|цахим\s+шуудан)|'
                            r'\s+(?:ямар(?:\s+ямар)?|юу)\s+хичээл\s+заадаг|\s+юу\s+заадаг)', re.I)
# Right after «<нэр> багш»: «гэж хэн бэ», «хэн бэ», «-ийн талаар / тухай», «-ийг танилцуулна уу» ask who the teacher is.
# Code review 11/25: anywhere in the question it also caught «… багшийн тэнхимийн эрхлэгч хэн бэ?» and «… багшийн
# зурагтай танилцуулгыг үзье» (the website introduction with its picture), so only directly after the name.
WHO = re.compile(r'(?:\s+гэж)?\s+(?:хэн|ямар\s+хүн)\s+(?:бэ|вэ)(?!\w)|\s+гэж\s+хэн(?!\w)|(?:ийн)?\s+(?:талаар|тухай)(?!\w)|'
                 r'(?:ийг|ыг)?\s+танилцуул', re.I)
ROOM_ASK = re.compile(r'өрөө|тоот|давхар|хаана\s+(?:суудаг|байдаг|ажилладаг|байна|байрладаг)|хаашаа\s+оч', re.I)
# 11/25 (the user's example): words between a teacher's name and the question that change nothing —
# «Соронзонболд багш чинь хэн бэ?», «… багш маань …», «… гэдэг багш …».
NAME_PARTICLE = r'(?:чинь|маань|минь|гэдэг|гэгч|гэх)'
# A sentence after one that names a person, with no subject of its own, asks about that person: the room or
# floor, how or when to meet, the e-mail or phone, what they teach.
# After a named teacher: looking for them, going to them, whether they are in — all ask how to meet them.
MEET_ASK = re.compile(r'уулз|хайж|хайгаад|дээр\s+оч|руу\s+оч|очих\s+гэсэн|очмоор|өрөөндөө\s+(?:байгаа|байна)|'
                      r'одоо\s+(?:хаана|байгаа|байна|өрөөндөө)|хаана\s+байгаа|завтай|чөлөөтэй', re.I)
# 11/26 (7): the whole question after the name — «… багш байна уу», «… багш ирсэн үү», «… багшид яаж хандах вэ».
# Only the whole rest, so «… багшийн зураг байна уу» stays the website's introduction.
IN_ASK = re.compile(r'(?:(?:энд|сургууль\s+дээрээ?|ажил\s+дээрээ|ажилдаа)\s+)?(?:байна|байгаа|ирсэн)\s+(?:уу|юу|үү)|'
                    r'(?:яаж|хэрхэн)\s+ханд(?:ах|даг)(?:\s+(?:вэ|бэ))?', re.I)
LESSON_TIME_ASK = re.compile(r'(?:хэдэн\s+цагт|хэзээ)\s+хичээл|хичээл\w*\s+(?:нь\s+)?(?:хэдэн\s+цагт|хэзээ)', re.I)
LESSON_ROOM_ASK = re.compile(r'хичээл\w*\s+(?:нь\s+)?хаана|хаана\s+хичээл|аль\s+(?:анги|өрөө|танхим)\w*\s+хичээл', re.I)
OWN_CLASS_ASK = re.compile(r'(?:аль|ямар|хэддүгээр)\s+анги\w*\s+(?:багш|даа)|анги\s+даа|даасан\s+анги', re.I)
# A post said after a given name instead of «багш»: «Оюунжаргал захирал хаана суудаг вэ?»
POST_WORD = r'(?:захирал|эрхлэгч|менежер|мэргэжилтэн|эмч|нягтлан(?:\s+бодогч)?|номын\s+санч|сэтгэл\s+зүйч|ажилтан|гуай)'
PERSON_FOLLOWUP = re.compile(
    r'(?:(?:тэр|энэ)\s+(?:багш|хүн)\s+)?(?:нь\s+)?(?:'
    r'(?:хэдэн|хэддүгээр|аль|ямар)\s+(?:давхар|өрөө|тоот)|хаана\s+(?:суудаг|байдаг|ажилладаг|байна|байрладаг|вэ)|'
    r'хаашаа\s+оч|өрөө\s+нь|(?:(?:яаж|хэрхэн|хэзээ|хаана|хэдэн\s+цагт|одоо|өнөөдөр|маргааш)\s+)?(?:уулз|холбогд|холбоо\s+бар)|'
    r'(?:юу|ямар(?:\s+ямар)?\s+хичээл)\s+заадаг|(?:и-?мэйл|имэйл|мэйл|цахим\s+шуудан|утас|утасны\s+дугаар)(?!\w)|'
    r'(?:одоо|өнөөдөр|маргааш)\s+(?:хичээлтэй|чөлөөтэй|завтай|байгаа|байна))', re.I)
# 11/28 (the user's test): «Соронзонболд багш гэж хэн бэ? … 1 дэхь өдөр 09:00 цагт уулзах боломжтой болов уу?» — a
# sentence that starts with a day or an hour and asks to meet, whether the person is free, has a lesson or is in, is
# about the person named before (it went to the website and showed an entrance-exam time).
TIMED_FOLLOWUP = re.compile(TIME_LEAD + MEET_OR_FREE, re.I)
# 11/28 (2), the user's test: «… бусад багш нар нь хэн бэ» after a teacher asks who else works in that teacher's
# department.
COLLEAGUES = re.compile(r'(?:нь\s+)?(?:(?:тэр|энэ)\s+тэнхимийн\s+|тэнхимийн\s+)?(?:бусад|хамт\s+ажилладаг)\s+'
                        r'(?:багш(?:\s*нар)?|ажилтн(?:ууд|ы)|хүмүүс)(?:\s+нь)?\s+'
                        r'(?:хэн(?:\s+хэн)?|хэд|хэдэн|нэрс|жагсаалт)', re.I)
# A subject carried to a later part is a noun phrase: «Маргааш 10 цагт уулзаж болох уу, имэйл нь юу вэ» carried
# «Маргааш 10 цагт уулзаж» into the e-mail part (11/28 (2)). No number, day, hour or verb form.
NOT_A_SUBJECT = re.compile(r'\d+(?![\d:.])(?!\s*(?:тоот|-?р\s+өрөө))|\d+[:.]\d|(?<!\w)(?:өнөөдөр|маргааш|нөгөөдөр|одоо|цаг\w*|гараг\w*|даваа|мягмар|лхагва|пүрэв|'
                           r'баасан|бямба|ням|уулз\w*|холбогд\w*|байх|байна|байгаа|болох|болно|ирэх|очих|маань|минь|'
                           r'\w+(?:вал|вэл|вол|вөл|бал|бэл|бол|бөл)|\w{3,}(?:аад|ээд|оод|өөд))(?!\w)', re.I)
# 11/28 (3), the user's chat: «… хэддүгээр ангиас ордог вэ …» then «тэгвэл очиж уулзая гэвэл хэнтэй уулзах вэ» — who to go
# to about what was just asked; «олдсонгүй» was shown.
WHO_TO_ASK = re.compile(r'(?:(?:за|тэгвэл|тэгэхээр|тэгээд|тэгэх\s+юм\s+бол)\s*,?\s+)?'
                        r'(?:(?:очиж\s+|биечлэн\s+)?(?:уулзъя|уулзая|уулзмаар|уулзах|асуух|лавлах|очъё|очих)\s+(?:гэвэл|бол|гэсэн\s+юм|гэж\s+байна)\s*,?\s+)?'
                        r'(?:хэнтэй\s+уулз\w*|хэнд\s+ханд\w*|хэнээс\s+асуу\w*|хаашаа\s+оч\w*|хаана\s+оч\w*|хаана\s+ханд\w*)'
                        r'\s+(?:вэ|бэ)\s*[?？.!]*\s*', re.I)
WEEKDAY = re.compile(r'(?<!\w)(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)', re.I)
DAY_WORD = re.compile(r'(?<!\w)(өнөөдөр|маргааш|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)', re.I)
TEACHER = re.compile(r'(?<![\w.])([А-ЯӨҮЁ])\.\s*([А-ЯӨҮЁ][а-яөүё-]{2,})\s+багш', re.I)
# Parallel asked values sharing one predicate: «…хэдэн оюутан» + «хэдэн багш оролцсон бэ».
PARALLEL_HEAD = re.compile(r'^(?P<subject>.*?)(?P<ask>(?<!\w)(?:хэдэн|хэд|хэддүгээр|ямар)\s+[\w-]+)$', re.I)
PARALLEL_TAIL = re.compile(r'^(?P<ask>(?:хэдэн|хэд|хэддүгээр|ямар)\s+[\w-]+)\s+(?P<predicate>\S.*)$', re.I)
PARTICLES = frozenset('вэ бэ уу үү юу юм'.split())
# Finite verb endings («байна», «байдаг», «оролцсон»); a counted noun («удаа», «оюутан») keeps none.
VERB_END = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх)$')
# Words that ask about a property of the thing already named («Имэйл нь юу вэ?», «Хэддүгээр
# давхарт байдаг вэ?»), not a new topic, when a follow-up borrows the previous question's thing.
FOLLOWUP_ATTRIBUTES = frozenset(('утас', 'имэйл', 'цахим шуудан', 'хаяг', 'өрөө', 'давхар', 'тоот', 'байрлах',
                                 'байрладаг', 'багш', 'анги', 'бүлэг', 'хуваарь', 'уулзах', 'эрхлэгч', 'холбоо барих'))
SPOKEN_DIGITS = NUMBER_UNITS
# Round 20: a polite opening («Уучлаарай, …», «Сайн байна уу, …») or a short self-introduction («Би шинэ оюутан,
# …») before the question; its comma kept the desk's lookups from reading «номын сан хаана байдаг вэ».
COURTESY = re.compile(r'(?:\s*(?:уучлаарай|өршөөгөөрэй|сайн\s+(?:байна\s+|байцгаана\s+)?уу|байна\s+уу|надад\s+тусална\s+уу|'
                      r'туслаач|нэг\s+юм\s+асууя|асуух\s+юм\s+байна|би\s+(?:шинэ\s+)?(?:оюутан|элсэгч|эцэг\s+эх|зочин)|'
                      r'би\s+элсэх\s+гэсэн\s+юм|'
                      # 11/28 (3), long chats: an answer acknowledged before the next question («за ойлголоо, …»).
                      r'ойлголоо|ойлгосон|ойлгомжтой|баярлалаа|за\s+тэгье|тийм\s+үү|за\s+за|болж\s+байна)\s*[,!.]+|\s*сайн\s+(?:байна\s+|байцгаана\s+)?уу\s*[?？]+'
                      # 11/28 (6) sweep: «сайн байна уу Зоригт багш хаана байдаг вэ» — no comma, two words or more after it.
                      r'|\s*сайн\s+(?:байна\s+|байцгаана\s+)?уу(?=\s+\S+\s+\S))+\s*(?=\S)', re.I)


def _without_courtesy(text):
    """The question without its polite opening, and whether one was there."""
    courtesy = COURTESY.match(text) if isinstance(text, str) else None
    if not courtesy:
        return text, False
    rest = text[courtesy.end():].strip()
    return rest[:1].upper() + rest[1:], True
GREETING = re.compile(r'(?:сайн\s+(?:байна\s+|байцгаана\s+)?уу|баярлалаа|hello|hi)', re.I)
# A wish to get a paper (round 9); only papers, so «Шалгалт авах …» (an exam) and «Мэдээлэл авмаар байна»
# (broad information, which has its own clarification) stay as asked (review).
REQUEST = re.compile(r'(.{0,60}?(?:тодорхойлолт|хуудас|үнэмлэх|карт|гэрчилгээ|диплом|лавлагаа|маягт|анкет|'
                     r'гэрээ|өргөдөл|хуулбар)\w*)\s+ав(?:ах\s+гэсэн(?:\s+юм)?|маар\s+байна|ъя|ах\s+хэрэгтэй\s+байна)'
                     r'\s*[.!?]*', re.I)
COURSE = re.compile(r'(?<!\d)([1-5])\s*(?:-?\s*(?:р|дугаар|дүгээр|дахь|дэх)\b)?\s*курс\w*', re.I)


def other_time_but_clock(text):
    """A named other day («маргааш», «даваа») in a lesson-time question; «хэдэн цагт» itself is no other time."""
    return re.search(r'маргааш|өчигдөр|нөгөөдөр|(?<!\w)(?:даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)|\d{1,2}:\d{2}',
                     text, re.I) is not None


def _words(text):
    return re.findall(r'[\w.-]+', text.casefold())


def _stem(word):
    return word.casefold()[:5]


def _comitative(word):
    """«зүйч» -> «зүйчтэй», «Захирал» -> «Захиралтай», «Болд» -> «Болдтой»: the word's last vowel other
    than «и» chooses the ending (round 16)."""
    last = last_vowel(word) or 'э'
    return word + ('той' if last in 'оё' else 'тай' if last in 'аяуюы' else 'тэй')


def _office_stem(word):
    # «албаны» and «алба» meet at «алба»; a five-letter cut would not (11/17).
    from mongolian_morphology import light_stem
    return light_stem(word.casefold())


# ---- everyday wordings (2026-11-26) ---------------------------------------------------------------------------------
# The user: «энэ яадаг сургууль вэ» got «not found»; «when I ask one different question the system collapses». A sweep
# of 130 everyday questions showed the kinds below. Each maps the whole question (one sentence, casefolded, without
# punctuation) to the stored or table question that answers it; every guard of the route still applies to that one.
SCHOOL_OVERVIEW_QUESTION = 'Шинэ Монгол технологийн коллеж ямар сургууль вэ?'
SCHOOL_HISTORY_QUESTION = 'Сургууль хэзээ байгуулагдсан бэ?'
ADMISSION_QUESTION = 'Элсэхэд ямар шаардлагатай вэ?'
_THIS = r'(?:(?:энэ|танай|танайх|манай|энд|ер\s+нь)\s+)?'
_END = r'(?:\s+(?:вэ|бэ|юм|юм\s+бэ|юм\s+вэ|уу|юу|үү))?'
EVERYDAY_QUESTIONS = tuple((re.compile(pattern), question) for pattern, question in (
    # What the school is: «энэ яадаг сургууль вэ», «энэ юуны сургууль вэ», «юу заадаг газар вэ», «энд юу хийдэг газар вэ».
    (_THIS + r'(?:(?:сургууль|коллеж|газар)\s+)?(?:чинь\s+)?(?:яадаг|юуны|ямар|юу\s+(?:хийдэг|заадаг|сургадаг|сурдаг))\s+'
     r'(?:сургууль|коллеж|газар)' + _END, SCHOOL_OVERVIEW_QUESTION),
    (_THIS + r'(?:сургууль|коллеж|газар)\s+(?:чинь\s+)?(?:юу|юуг)\s+(?:заадаг|хийдэг|сургадаг)' + _END, SCHOOL_OVERVIEW_QUESTION),
    (r'энд\s+(?:юу|юуг)\s+(?:сурдаг|заадаг|хийдэг|сургадаг)(?:\s+газар)?' + _END, SCHOOL_OVERVIEW_QUESTION),
    (r'(?:шмтк|коосэн|коллеж|nmct)\s+(?:гэж|гэдэг(?:\s+(?:нь|чинь))?)\s+(?:юу|ямар\s+сургууль)' + _END, SCHOOL_OVERVIEW_QUESTION),
    (r'(?:шмтк|nmct)\s+(?:юу\s+гэсэн\s+үг|гэдэг\s+(?:нь|чинь)\s+юу)' + _END, SCHOOL_OVERVIEW_QUESTION),
    # «энэ сургуулийн онцлог нь яг юу юм» (the user's chat 11/28 (3): «яг» was not read).
    (_THIS + r'(?:сургууль|сургуулийн|коллеж|коллежийн)\s+(?:гол\s+)?онцлог\w*(?:\s+нь)?(?:\s+(?:яг|гол))?(?:\s+(?:юу|ямар))?' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    (r'яагаад\s+(?:энэ\s+сургуульд|энд|танай\s+сургуульд|танайд|шмтк-д)\s+(?:сурах|суралцах|орох)(?:\s+ёстой)?' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    (_THIS + r'(?:сургууль|коллеж)\s+(?:сайн|япон(?:\s+сургууль)?)' + _END, SCHOOL_OVERVIEW_QUESTION),
    # The school's age: «хэдэн онд байгуулагдсан бэ», «сургууль хэдэн жилийн настай вэ».
    (_THIS + r'(?:(?:сургууль|шмтк|коллеж)\s+)?(?:хэдэн\s+онд|хэзээ)\s+(?:байгуулагдсан|байгуулсан|нээгдсэн|үүсгэн\s+байгуулагдсан)'
     + _END, SCHOOL_HISTORY_QUESTION),
    (_THIS + r'(?:(?:сургууль|шмтк|коллеж)\s+)?хэдэн\s+(?:жилийн\s+)?настай' + _END, SCHOOL_HISTORY_QUESTION),
    # A wish to enrol and the grade of entry: «хүүхдээ оруулах гэсэн юм», «9 төгсөөд орж болох уу», «12-р анги
    # төгссөн хүүхэд орж болох уу» — the admission answer says who may register for which course.
    # «орох», «сурах» alone may be entering a room or a lesson (code review 11/26): only with a school word.
    (r'(?:хүүхдээ|охиноо|хүүгээ|дүүгээ)\s+(?:(?:энд|танайд|танай\s+сургуульд|энэ\s+сургуульд|сургуульд)\s+)?'
     r'(?:оруулах|элсүүлэх|оруулъя)\s+(?:гэсэн|гэж\s+байгаа|гэж\s+байна)(?:\s+юм)?(?:\s+аа)?', ADMISSION_QUESTION),
    (r'(?:би\s+)?(?:(?:энд|танайд|танай\s+сургуульд|энэ\s+сургуульд|сургуульд)\s+)?(?:элсэх|суралцах)\s+'
     r'(?:гэсэн|гэж\s+байгаа|гэж\s+байна)(?:\s+юм)?(?:\s+аа)?', ADMISSION_QUESTION),
    (r'(?:би\s+)?(?:танайд|танай\s+сургуульд|энэ\s+сургуульд|сургуульд)\s+(?:орох|сурах)\s+'
     r'(?:гэсэн|гэж\s+байгаа|гэж\s+байна)(?:\s+юм)?(?:\s+аа)?', ADMISSION_QUESTION),
    (r'(?:(?:хүүхэд|охин|хүү|би|миний\s+хүүхэд)\s+)?\d{1,2}(?:\s*-?\s*(?:р|дугаар|дүгээр))?(?:\s+анги)?\s+'
     r'(?:төгсөөд|төгссөн|төгсөж\s+байгаа)(?:\s+(?:хүүхэд|сурагч|хүн))?\s+(?:(?:энд|танайд|танай\s+сургуульд)\s+)?'
     r'(?:орж|элсэж|суралцаж)\s+(?:болох|болно)' + _END, ADMISSION_QUESTION),
    (r'элсэлтийн\s+шалгалт(?:\s+(?:өгөх|өгдөг|авдаг|авах|байдаг|байна))?' + _END, ADMISSION_QUESTION),
    (r'(?:элсэлтийн\s+)?бүртгэл(?:ээ)?\s+(?:хаана|яаж)\s+(?:хийдэг|хийх|явагддаг|бүртгүүлэх|өгөх)' + _END
     + r'|(?:хаана|яаж)\s+бүртгүүлэх' + _END, ADMISSION_QUESTION),
    (r'(?:элсэхэд\s+)?(?:ямар\s+(?:ямар\s+)?)?(?:бичиг\s+баримт|материал)\s+(?:бүрдүүлэх|бүрдүүлдэг|авчрах|хэрэгтэй|шаардлагатай|өгөх)'
     + _END, 'Элсэхэд ямар бичиг баримт хэрэгтэй вэ?'),
    # IT and programming: the computer science department (not a question who teaches it or where).
    (r'(?!.*(?:хэн|хаана|хэзээ|цагт|өрөө|багш))(?=.*(?:программист|програмист|программ\s*хангамж|програм\s*хангамж|'
     r'программчлал|програмчлал|(?<!\w)ай\s*ти(?!\w)|(?<!\w)it(?!\w)|мэдээллийн\s+технологи|кодлол|код\s+бичих))'
     r'.*(?:мэргэжил|хөтөлбөр|сурах|сурч|суралц|байна\s+уу|бий\s+юу|байдаг\s+уу|заадаг\s+уу|сургадаг\s+уу|болох\s+уу).*',
     'Компьютерын ухааны тэнхимийн талаар тайлбарлана уу.'),
    # 11/26 (2), a second sweep of 101 random questions: wordings of questions the tables and the stored answers hold.
    (r'өнөөдөр\s+хичээл(?:тэй)?(?:\s+(?:байгаа|байна|орох|ордог))?' + _END, 'Өнөөдөр хичээлтэй юу?'),
    (r'(?:нэг\s+)?(?:хичээл|цаг)\s+хэдэн\s+минут(?:\s+(?:ордог|үргэлжилдэг|байдаг))?' + _END,
     'Нэг хичээл хэдэн минут үргэлжилдэг вэ?'),
    (r'(?:эхний|1-р|нэгдүгээр)\s+(?:цаг|хичээл)\s+хэд(?:эн\s+цаг)?(?:ээс|т|аас)?(?:\s+(?:эхэлдэг|ордог))?' + _END
     + r'|хичээл\s+хэдээс\s+(?:эхэлдэг|ордог)' + _END, 'Хичээл хэдэн цагт эхэлдэг вэ?'),
    (r'(?:даваа|мягмар|лхагва|пүрэв|баасан)\s+гараг(?:т)?\s+(?:сургууль\s+)?(?:ажиллах|ажилладаг|нээлттэй)' + _END,
     'Сургууль хэдэн цагт ажилладаг вэ?'),
    (r'(?:(?:коосэн|сургуулиа|сургууль|энд|шмтк)\s+)?төгсөөд\s+юу\s+(?:болох|болдог|хийх|хийдэг)' + _END
     + r'|төгсөөд\s+(?:их\s+)?сургуульд\s+(?:орж|дэвшиж|үргэлжлүүлэн\s+суралцаж)\s+(?:болох|болно)' + _END
     # 11/28 (6) sweep: «энд сурвал ямар ажилд орох вэ»
     + r'|(?:(?:энд|танайд|энэ\s+сургуульд)\s+)?(?:сурвал|суралцвал|төгсвөл|сурснаар|төгссөнөөр)\s+(?:ямар\s+){1,2}(?:ажил(?:д|тай)?|мэргэжилтэй)\s+'
       r'(?:орох|ордог|болох|болдог|ажиллах|ажилладаг)' + _END,
     '5-р курс төгссөний дараа ямар зам байдаг вэ?'),
    (r'(?:манай|миний)\s+(?:хүүхэд|охин|хүү|дүү)\s+\d{1,2}(?:\s*-?\s*р)?\s+ангид\s+сурдаг\s+'
     r'(?:элсүүлмээр|оруулмаар|элсүүлэх|оруулах)(?:\s+(?:байна|гэсэн\s+юм|гэж\s+байна))?'
     r'|(?:хүүхдээ\s+)?(?:элсүүлмээр|элсмээр)\s+байна', ADMISSION_QUESTION),
    (r'(?:(?:танайд|энд|сургуульд)\s+)?(?:япон|англи)\s+хэл\s+(?:заадаг|ордог|үздэг|сурдаг)' + _END,
     'Япон хэл, Англи хэлний хичээл түвшингээр ордог уу?'),
    (r'хэдэн\s+төгрөгөөр\s+(?:сурах|суралцах|сурдаг)' + _END
     + r'|(?:сургалтын\s+)?төлбөр\s+(?:нь\s+)?(?:хэдэн\s+төгрөг|ямар\s+үнэтэй|үнэтэй)' + _END, 'Сургалтын төлбөр хэд вэ?'),
    (_THIS + r'(?:сургууль\s+)?хэдэн\s+(?:анги(?:\s+танхим)?|лаборатори|танхим)(?:тай|той|тэй)' + _END, 'Сургалтын орчин ямар вэ?'),
    (_THIS + r'(?:сургуулийн\s+)?барилга\s+(?:хэр\s+том|ямар)' + _END, 'Сургалтын орчин ямар вэ?'),
    (_THIS + r'(?:сургууль\s+)?япон(?:той|\s+улстай)\s+(?:ямар\s+)?(?:холбоотой|хамааралтай)' + _END, SCHOOL_OVERVIEW_QUESTION),
    # Only the admission exam named as such: a student's «шалгалт хэзээ эхлэх вэ» is about term exams (code review).
    (r'элсэлтийн\s+шалгалт\s+хэзээ\s+(?:болох|болдог|авах|авдаг|эхлэх)' + _END, 'Элсэлтийн шалгалт хэзээ болдог вэ?'),
    # 11/26 (3), the user's spoken example: «Энэ хэддүгээр ангиасаа ордог сургууль вэ? 10-р ангиасаа ордог юм уу?
    # Орохдоо юу юу бүртгүүлэх хэрэгтэй вэ?»
    (_THIS + r'(?:сургууль(?:д)?\s+)?(?:хэддүгээр|хэдэн|ямар|аль)\s+анги(?:ас|аас|иас)(?:аа)?\s+'
     r'(?:ордог|элсдэг|авдаг|орох|элсэх|элсүүлдэг|орж\s+болох|элсэж\s+болох)(?:\s+боломжтой)?(?:\s+(?:сургууль|газар))?'
     + _END, ADMISSION_QUESTION),
    (_THIS + r'\d{1,2}(?:\s*-?\s*р)?\s+анги(?:ас|аас|иас)(?:аа)?\s+(?:ордог|элсдэг|авдаг|орох|элсэх|элсүүлдэг|орж\s+болох)' + _END,
     ADMISSION_QUESTION),
    (r'(?:орохдоо|ороход|элсэхдээ|элсэхэд|бүртгүүлэхэд|бүртгүүлэхдээ)\s+(?:'
     r'юу(?:\s+юу)?\s+(?:бүртгүүлэх|бүрдүүлэх|авчрах|өгөх|авч\s+ирэх)'
     r'|ямар\s+(?:ямар\s+)?(?:бичиг\s+)?(?:баримт|материал)(?:\s+(?:бүртгүүлэх|бүрдүүлэх|авчрах|өгөх|авч\s+ирэх))?'
     r')(?:\s+(?:хэрэгтэй|шаардлагатай))?' + _END,
     'Элсэхэд ямар бичиг баримт хэрэгтэй вэ?'),
    # 11/26 (4), the user's own test: «энд сурснаар ямар давуу талуудтай вэ» found nothing.
    (r'(?:(?:энд|танайд|энэ\s+сургуульд|танай\s+сургуульд|шмтк-д)\s+)?(?:сурснаар|сурвал|суралцсанаар|суралцвал|элсвэл|орвол)\s+'
     r'(?:ямар\s+){0,2}(?:давуу\s+тал\w*|ашиг\s*тус\w*|ашигтай|онцлог\w*)(?:\s+(?:байдаг|байна))?' + _END
     + r'|' + _THIS + r'(?:сургуулийн|коллежийн|сургууль|коллеж)\s+(?:нь\s+)?(?:ямар\s+)?давуу\s+тал\w*(?:\s+(?:нь\s+)?юу)?' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    # 11/28 (5), the user: «хичээлийн онцлог нь юу вэ» found nothing — what the teaching is like is the school's own
    # introduction (Japanese kosen system, general and engineering education, five-year programme).
    (r'(?:(?:энэ\s+|танай\s+)?(?:сургуулийн|коллежийн)\s+)?(?:хичээлийн|сургалтын|хичээл\s+заах|сургалт\s+явуулах)\s+'
     r'(?:гол\s+)?онцлог\w*(?:\s+нь)?(?:\s+(?:яг|гол))?(?:\s+(?:юу|ямар))?' + _END, SCHOOL_OVERVIEW_QUESTION),
    # 11/28 (5) sweep of school-general wordings: «энд сурах ямар ашигтай вэ», «шмткийн онцлог юу вэ», «сургалт нь ямар
    # байдаг вэ», «ямар хичээлүүд ордог вэ» found nothing or a fragment; the school's own introduction answers them.
    (r'(?:энд|танайд|энэ\s+сургуульд|танай\s+сургуульд)\s+(?:сурах|суралцах)\s+(?:нь\s+)?(?:ямар\s+){0,2}'
     r'(?:ашигтай|ашиг\s*тустай|давуу\s+талтай|давуу\s+тал\w*)' + _END, SCHOOL_OVERVIEW_QUESTION),
    (r'(?:шмтк|шмткийн|шмтк-ийн|коосэн\s+сургуулийн|коосэнгийн)\s+(?:гол\s+)?(?:онцлог|давуу\s+тал)\w*(?:\s+нь)?(?:\s+(?:юу|ямар))?' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    (r'(?:(?:энэ\s+|танай\s+)?(?:сургуулийн|коллежийн)\s+)?(?:сургалт|хичээл)\s+(?:нь\s+)?ямар\s+(?:байдаг|байна|явагддаг|орно)' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    (r'(?:энд\s+|энэ\s+сургуульд\s+)?ямар\s+(?:ямар\s+)?хичээл(?:үүд)?\s+(?:ордог|заадаг|үздэг|судалдаг|сурдаг)' + _END,
     SCHOOL_OVERVIEW_QUESTION),
    # 11/28 (6) sweep: «би шинэ оюутан» said alone showed a quality-survey line; it is a greeting that asks for help.
    (r'би\s+(?:шинэ\s+)?(?:оюутан|элсэгч|эцэг\s+эх|зочин|ажилтан)(?:\s+(?:байна|юм))?' + _END, 'Надад тусална уу?'),
    # Where the teachers sit, Wi-Fi, how to get to the school.
    (r'багш\s+нар(?:ын)?(?:\s+өрөө)?\s+хаана(?:\s+(?:суудаг|байдаг|байна|байрладаг))?' + _END, 'Багш нарын өрөө хаана вэ?'),
    (r'(?:(?:сургуульд|анги(?:\s+танхим)?д|энд)\s+)?(?:wi-?fi|вай\s*фай|утасгүй\s+интернэт|интернэт)'
     r'(?:\s+(?:байдаг|байна|бий|ашиглаж\s+болох))?' + _END, 'Сургалтын орчин ямар вэ?'),
    (r'(?:(?:сургууль(?:д|руу)|энд|танайд|танай\s+сургууль\s+руу)\s+)?(?:(?:автобусаар|машинаар|юугаар|яаж)\s+)+'
     r'(?:очих|ирэх|хүрэх|явах)' + _END, 'Сургуулийн хаяг хаана вэ?'),
))
# A department asked what it teaches or what it is like: the stored introduction of that department.
DEPARTMENT_ABOUT = re.compile(r'(механик|хими|химийн|барилга|барилгын|цахилгаан|цахилгааны|компьютер|компьютерын|ерөнхий\s+эрдмийн)'
                              r'(?:\s+инженер(?:ийн|ээр)?)?(?:\s+тэнхим(?:ийн)?)?(?:\s+(?:хөтөлбөр|мэргэжил)(?:ийн)?)?\s+'
                              r'(?:ямар\s+мэргэжил|юу\s+(?:сурдаг|заадаг|сургадаг)|юуг\s+заадаг|тухай|талаар|онцлог(?:\s+нь)?(?:\s+юу)?)'
                              r'(?:\s+(?:вэ|бэ|хэлж\s+өгөөч|хэлнэ\s+үү))?')
DEPARTMENT_INTRO = (('механик', 'Механик инженерийн тэнхимийн талаар танилцуулна уу.'),
                    ('хими', 'Химийн инженерийн тэнхимийн талаар танилцуулна уу.'),
                    ('барилг', 'Барилга, дэд бүтцийн инженерийн тэнхимийн талаар танилцуулна уу.'),
                    ('цахилгаан', 'Цахилгаан электроникийн инженерийн тэнхимийн талаар танилцуулна уу.'),
                    ('компьютер', 'Компьютерын ухааны тэнхимийн талаар тайлбарлана уу.'),
                    ('ерөнхий', 'Ерөнхий эрдмийн тэнхимийн талаар танилцуулна уу.'))
# A department head asked by the department's short name: «цахилгааны тэнхимийн эрхлэгч» found nothing (the website
# names it «Цахилгаан электроникийн инженерийн тэнхим»); the other four short names already find their heads (11/26).
# Only before «эрхлэгч»: «Цахилгааны тэнхимийн багш нар» is answered from the tables.
DEPARTMENT_HEAD = re.compile(r'(?<!\w)цахилгаан(?:ы)?\s+(?=тэнхимийн\s+эрхлэгч)', re.I)
DEPARTMENT_HEAD_NAME = 'Цахилгаан электроникийн инженерийн '
# Only the whole word with a case ending, not «дарга нар» or «даргын зөвлөл», and not another school's head
# («ерөнхий боловсролын сургуулийн дарга») — code review.
SCHOOL_HEAD = re.compile(r'(?<!боловсролын\s)(?<!\w)(?:сургуулийн|коллежийн)\s+дарга(тай|д|аас|ыг)?(?!\w)(?!\s+нар)', re.I)
SCHOOL_HEAD_FORMS = {None: 'захирал', 'тай': 'захиралтай', 'д': 'захиралд', 'аас': 'захирлаас', 'ыг': 'захирлыг'}
# A question of one topic word: the question a visitor at the desk means by it.
TOPIC_WORDS = {
    'төлбөр': 'Сургалтын төлбөр хэд вэ?', 'сургалтын төлбөр': 'Сургалтын төлбөр хэд вэ?', 'төлбөр хэд': 'Сургалтын төлбөр хэд вэ?',
    'элсэлт': ADMISSION_QUESTION, 'элсэх': ADMISSION_QUESTION, 'элсэлтийн шаардлага': ADMISSION_QUESTION,
    'элсэлтийн шалгалт': ADMISSION_QUESTION, 'захирал': 'Захирал хэн бэ?', 'хаяг': 'Сургуулийн хаяг хаана вэ?',
    'сургуулийн хаяг': 'Сургуулийн хаяг хаана вэ?', 'утас': 'Сургуулийн холбоо барих мэдээллийг хэлнэ үү.',
    'утасны дугаар': 'Сургуулийн холбоо барих мэдээллийг хэлнэ үү.', 'холбоо барих': 'Сургуулийн холбоо барих мэдээллийг хэлнэ үү.',
    'имэйл': 'Сургуулийн холбоо барих мэдээллийг хэлнэ үү.', 'тэтгэлэг': 'Тэтгэлэг байдаг уу?',
    'дадлага': 'Японы компанид дадлага хийх боломжтой юу?', 'мэргэжил': 'Ямар мэргэжлээр сургадаг вэ?',
    'мэргэжлүүд': 'Ямар мэргэжлээр сургадаг вэ?', 'хөтөлбөр': 'Ямар мэргэжлээр сургадаг вэ?',
    'тэнхим': 'Сургууль хэдэн тэнхимтэй вэ?', 'тэнхимүүд': 'Сургууль хэдэн тэнхимтэй вэ?', 'дотуур байр': 'Дотуур байр байдаг уу?',
    'хоолны газар': 'Сургуульд хоолны газар бий юу?', 'гуанз': 'Сургуульд хоолны газар бий юу?',
    'спорт заал': 'Сургуульд спорт заал бий юу?', 'хичээлийн хуваарь': 'Хичээл хэдэн цагт эхэлдэг вэ?',
    'цайны цаг': 'Цайны цаг хэзээ вэ?', 'ажлын цаг': 'Сургууль хэдэн цагт ажилладаг вэ?', 'түүх': SCHOOL_HISTORY_QUESTION,
    'сургуулийн түүх': SCHOOL_HISTORY_QUESTION, 'эрхэм зорилго': 'Сургуулийн эрхэм зорилго юу вэ?',
    'карьерын төв': 'Карьерын төв юу хийдэг вэ?', 'оюутны зөвлөл': 'Оюутны зөвлөл юу хийдэг вэ?',
    'бүртгэл': 'Элсэлтийн бүртгэл хэзээ явагддаг вэ?', 'вэбсайт': 'Сургуулийн вэбсайт юу вэ?', 'вэб сайт': 'Сургуулийн вэбсайт юу вэ?',
    'wifi': 'Сургалтын орчин ямар вэ?', 'wi-fi': 'Сургалтын орчин ямар вэ?', 'шмтк': SCHOOL_OVERVIEW_QUESTION,
    'коосэн': SCHOOL_OVERVIEW_QUESTION,
}
# 11/27: «Би элсэлтийн талаар мэдмээр байна» found nothing. A wish to know about a topic word asks the same as the word
# alone; the word is said in the genitive before «талаар / тухай». A wish verb is required: a bare «… талаар» may name
# a website page section (website_sections.py).
ABOUT_WISH = re.compile(
    r'(?:(?:би|надад|та|танаас)\s+)?(?:(?:энэ|танай|манай)\s+)?(?:(?:сургуулийн|коллежийн)\s+)?(?P<topic>.+?)\s+(?:талаар|тухай)\s+'
    r'(?:(?:дэлгэрэнгүй|илүү|сайн)\s+)?(?:мэдээлэл\s+)?(?:'
    r'мэдмээр|мэдэхийг\s+(?:хүсч|хүсэж|хүсээд)|мэдэх\s+гэсэн|асуумаар|асуух\s+гэсэн|асуух\s+юм|сонирхож|сонирхсон|'
    r'авмаар|авах\s+гэсэн|сонсмоор|хэлж\s+өгөөч|хэлж\s+өгнө\s+үү|ярьж\s+өгөөч|тайлбарлаж\s+өгөөч|өгнө\s+үү|өгөөч|хэрэгтэй)'
    r'(?:\s+(?:байна|байгаа|байсан))?(?:\s+(?:юм|аа|л))*(?:\s+(?:уу|юу))?')
# The genitive of the topic words a visitor names before «талаар».
TOPIC_GENITIVE = {
    'элсэлтийн': 'элсэлт', 'төлбөрийн': 'төлбөр', 'сургалтын төлбөрийн': 'сургалтын төлбөр', 'мэргэжлийн': 'мэргэжил',
    'мэргэжлүүдийн': 'мэргэжлүүд', 'хөтөлбөрийн': 'хөтөлбөр', 'тэтгэлгийн': 'тэтгэлэг', 'дадлагын': 'дадлага',
    'дотуур байрны': 'дотуур байр', 'тэнхимийн': 'тэнхим', 'тэнхимүүдийн': 'тэнхимүүд', 'түүхийн': 'түүх',
    'бүртгэлийн': 'бүртгэл', 'элсэлтийн шалгалтын': 'элсэлтийн шалгалт', 'элсэлтийн шаардлагын': 'элсэлтийн шаардлага',
    'карьерын төвийн': 'карьерын төв', 'оюутны зөвлөлийн': 'оюутны зөвлөл', 'хоолны газрын': 'хоолны газар',
    'спорт заалны': 'спорт заал', 'хичээлийн хуваарийн': 'хичээлийн хуваарь', 'эрхэм зорилгын': 'эрхэм зорилго',
}
# «<алба/өрөө> байна уу», «… бий юу», «… байдаг уу»: whether an office exists is answered by where it is.
EXISTS_ASK = re.compile(r'(?:сургуульд\s+|энд\s+)?(.+?)\s+(?:байна|байдаг|бий)\s+(?:уу|юу)')
# «гадаад харилцааны алба хаана байдаг вэ»: the office the table names «Гадаад харилцаа, карьер хөгжлийн төв».
FOREIGN_OFFICE = re.compile(r'гадаад\s+харилцаа(?:ны)?(?:\s+(?:алба|төв|хэлтэс))?\s+хаана(?:\s+(?:байдаг|байна|байрладаг))?'
                            r'(?:\s+(?:вэ|бэ))?')
BARE_ROOM = re.compile(r'([a-zа-яөүё]?\d{3,4}[a-zа-яөүё]?)\s+(?:өрөө\s+)?(?:хаана|хэддүгээр\s+давхарт)(?:\s+(?:байдаг|байна|вэ|бэ))*')

# Typing without vowels («сургалтын тлбр хэд вэ», «элслт хзэ вэ»): a word of consonants alone is read as the one known
# word with the same consonants. The first letter stays (a word may begin with a vowel: «элслт»); «й», «ь», «ъ» count as
# vowels (people drop «й» too: «бдг»). Only Cyrillic lower-case words of three letters or more; an upper-case word is an
# abbreviation («ШМТК»); a skeleton two known words share is left as typed.
VOWELS = set('аэиоуөүеёюяыйьъ')
KNOWN_WORDS = ('төлбөр төлбөрийн төлбөрөө сургалтын сургууль сургуулийн сургуульд элсэлт элсэлтийн элсэх элсэхэд бүртгэл '
               'бүртгэлийн хураамж хураамжийн шалгалт шалгалтын мэргэжил мэргэжлийн тэнхим тэнхимийн багш багшийн өрөө '
               'өрөөнд давхар давхарт хичээл хичээлийн хуваарь хуваарийн хаана хэзээ хэдэн байдаг байна байгаа байрладаг '
               'ажилладаг захирал захирлын номын сан алба албаны оюутан оюутны тэтгэлэг дадлага хаяг утас утасны имэйл '
               'цаг цагт эхэлдэг дуусдаг маргааш өнөөдөр уулзах ямар юу хоол хоолны дотуур байр түүх холбоо барих '
               'лаборатори ангийн курс курст анги шмтк коосэн').split()


def skeleton(word):
    """«төлбөр» -> «тлбр», «элсэлт» -> «элслт», «байдаг» -> «бдг»."""
    return word[:1] + ''.join(letter for letter in word[1:] if letter not in VOWELS)


class QuestionPlanner:
    def __init__(self, *, enabled=False, split_compound=False, class_groups=False, staff_names=False,
                 groups=None, given_names=None, topic_keywords=(), offices=(), staff=(), class_names=(), rooms=(),
                 posts=None):
        self.enabled = enabled is True
        # 11/26 (7): the tables' reader of a post said instead of a name («захирал маргааш 10 цагт завтай юу»).
        self.posts = posts if callable(posts) else None
        self.split_compound = self.enabled and split_compound is True
        self.class_groups = self.enabled and class_groups is True
        self.staff_names = self.enabled and staff_names is True
        self.groups = dict(groups or {})            # (department stem, course) -> group code
        self.given_names = dict(given_names or {})  # given name (casefold) -> full "Б.Сэлмаа"
        self.topic_keywords = tuple(keyword.casefold() for keyword in topic_keywords)
        self.offices = tuple(offices)                # service names in the reception rooms table
        # "б.сэлмаа" -> the table's own spelling, so the rewrite matches the reception lookup.
        self.staff = {re.sub(r'\s+', '', name.casefold()): name.strip() for name in staff}
        self.class_names = frozenset(class_names)    # every class group code in the table
        self.rooms = {str(name).casefold(): str(name) for name in rooms}   # room numbers: a bare «604 хаана вэ»
        # Known words for typing without vowels: the fixed list, the topics' keywords and the offices' names.
        known = set(KNOWN_WORDS) | {word for phrase in self.topic_keywords + tuple(name.casefold() for name in self.offices)
                                     for word in re.findall(r'[а-яөүё]+', phrase)}
        shapes = {}
        for word in known:
            if len(skeleton(word)) >= 3:
                shapes.setdefault(skeleton(word), set()).add(word)
        self.known_words = frozenset(known)
        # Words sharing a skeleton read as the shortest when it begins all the others («төлбөр» / «төлбөрөө»).
        self.vowelless = {shape: min(words, key=len) for shape, words in shapes.items()
                          if all(word.startswith(min(words, key=len)) for word in words)}

    @classmethod
    def from_config(cls, root, reception=None):
        root = Path(root)
        try:
            config = json.loads((root / CONFIG_PATH).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return cls()
        if config.get('schema_version') != 1 or config.get('enabled') is not True:
            return cls()
        tables = getattr(reception, 'tables', None) if getattr(reception, 'enabled', False) else None
        groups, names, offices, staff, class_names, rooms = {}, {}, [], [], [], []
        if tables is not None:
            seen = {}
            for group in tables.classes:
                department = (group.department or '').strip()
                if not department or not str(group.course).strip().isdigit():
                    continue
                key = (_stem(department.split()[0]), str(group.course).strip())
                seen.setdefault(key, set()).add(group.group)
            groups = {key: next(iter(values)) for key, values in seen.items() if len(values) == 1}
            owners = {}
            for full in [person.name for person in tables.staff] + [group.teacher for group in tables.classes]:
                match = re.fullmatch(r'\s*([А-ЯӨҮЁ])\.\s*([А-ЯӨҮЁа-яөүё-]{3,})\s*', full or '')
                if match:
                    owners.setdefault(match[2].casefold(), set()).add(match[1] + '.' + match[2])
            names = {given: next(iter(fulls)) for given, fulls in owners.items() if len(fulls) == 1}
            offices = [service.name for room in tables.rooms for service in room.services]
            staff = [person.name for person in tables.staff]
            class_names = [group.group for group in tables.classes]
            rooms = [room.name for room in tables.rooms]
        keywords = []
        try:
            domains = json.loads((root / 'config/knowledge-domains.json').read_text(encoding='utf-8'))['domains']
            keywords = [word for domain in domains.values() for word in domain.get('keywords', [])]
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        return cls(enabled=True, split_compound=config.get('split_compound'), class_groups=config.get('class_groups'),
                   staff_names=config.get('staff_names'), groups=groups, given_names=names, topic_keywords=keywords,
                   offices=offices, staff=staff, class_names=class_names, rooms=rooms,
                   posts=getattr(reception, 'post_question', None) if tables is not None else None)

    # -- rules ---------------------------------------------------------------
    @staticmethod
    def _unpunctuated(sentence):
        """«сургуульд яаж орох вэ хэддүгээр ангиас орох боломжтой вэ» -> two questions (11/26): speech and quick
        typing leave the question marks out. A cut after a question particle only when a second question follows:
        after «вэ / бэ» three words, or two with a question word; after «уу / үү» a question word before the last
        word («хувийн уу улсын уу», «бэлнээр төлөх үү дансаар шилжүүлэх үү» are one either-or question). A tail
        («… вэ мэдэх үү», «… вэ гэвэл …», «… уу үгүй юу») is no second question (code review 11/26)."""
        words = sentence.split()
        if len(words) < 5 or words[-1].casefold().strip('.!') not in ('вэ', 'бэ', 'уу', 'үү', 'юу', 'юү'):
            return [sentence]
        pieces, current = [], []
        for index, word in enumerate(words):
            current.append(word)
            rest = words[index + 1:]
            particle = word.casefold().rstrip('.!')
            # «… завтай юу ямар хичээл заадаг вэ» (11/28 (2) sweep): «юу» after «-тай / -гүй» asks yes or no.
            yes_no = particle == 'юу' and len(current) >= 2 and re.search(r'(?:тай|тэй|той|гүй)$', current[-2].casefold())
            if (particle not in ('вэ', 'бэ', 'уу', 'үү') and not yes_no) or len(current) < 2 or len(rest) < 2:
                continue
            if rest[0].casefold().strip('.!,') in NO_SECOND_QUESTION:
                continue
            asks = any(WH_WORD.fullmatch(other.casefold().strip('.!,')) for other in rest[:-1])
            if asks or (particle in ('вэ', 'бэ') and len(rest) >= 3):
                pieces.append(' '.join(current).rstrip('.!'))
                current = []
        if current:
            pieces.append(' '.join(current))
        return pieces

    def _split(self, query):
        sentences = [piece for s in re.split(r'[?？;]+', query) if s.strip() for piece in self._unpunctuated(s.strip())]
        parts = []
        for sentence in sentences:
            pieces = [p.strip() for p in re.split(r',\s*', sentence) if p.strip()]
            current = pieces[0]
            for piece in pieces[1:]:
                ends_ny = re.search(r'(?<!\w)нь\s*$', piece, re.I) and len(piece.split()) <= 3
                if QUESTION_WORD.search(current) and (QUESTION_WORD.search(piece) or ends_ny):
                    parts.append(current)
                    current = piece
                else:
                    current += ', ' + piece
            parts.append(current)
        if len(parts) < 2 or len(parts) > MAX_PARTS:
            return [query.strip()]
        return [part + '?' for part in parts]

    @staticmethod
    def _distribute(parts):
        """«X-д хэдэн оюутан, хэдэн багш оролцсон бэ?» asks two counts under one predicate: each
        part gets the shared subject (from the first) and predicate (from the last), 11/17 (5)."""
        texts = [part.rstrip('?？').strip() for part in parts]
        tail = PARALLEL_TAIL.match(texts[-1])
        heads = [PARALLEL_HEAD.match(text) for text in texts[:-1]]
        # A head must end in the asked noun («хэдэн оюутан»), not a verb or a particle: «Төлбөр
        # ямар байна?» is already a whole question (review 11/17 (5)).
        if (not tail or not all(heads) or not heads[0].group('subject').strip()
                or any(head.group('ask').split()[-1].casefold() in PARTICLES
                       or VERB_END.search(head.group('ask').split()[-1].casefold()) for head in heads)):
            return parts
        subject, predicate = heads[0].group('subject').strip(), tail.group('predicate').strip()
        return ([(head.group('subject').strip() or subject) + ' ' + head.group('ask') + ' ' + predicate + '?'
                 for head in heads] + [subject + ' ' + tail.group('ask') + ' ' + predicate + '?'])

    def _has_topic(self, text):
        words = [w for w in _words(text) if w not in FUNCTION_WORDS]
        if not words:
            return False
        lowered = text.casefold()
        if any(keyword in lowered for keyword in self.topic_keywords):
            return True
        return bool(re.search(r'[А-ЯӨҮЁA-Z]{2}-\d', text))

    @staticmethod
    def _subject(part):
        match = QUESTION_WORD.search(part)
        subject = part[:match.start()].strip(' ,') if match else ''
        # «Дотуур байр байдаг уу, хэдэн төгрөг вэ» (11/28 (3)): «байдаг» is no part of the thing asked about.
        return re.sub(r'(?:\s+(?:байдаг|байна|байгаа|бий|байх|болох|болдог|нь))+$', '', subject, flags=re.I).strip(' ,')

    def _person(self, text):
        """The teacher or staff member a part names («Н.Соронзонболд багш»), or None."""
        coded = self._class_code(text)[0]
        group = GROUP.search(coded)
        if group and re.match(r'\s+ангийн\s+багш', coded[group.end():]):
            return group.group(1) + ' ангийн багш'          # «КУ-2 ангийн багш хэн бэ? Хаана суудаг вэ? Имэйл нь?»
        named = self._named(coded)
        if named is None and not group:
            # «Уянга багш гэж хэн бэ?» — two staff share the name: the follow-up keeps it, and the tables ask which one
            # (11/28 (2) sweep: the follow-up lost the person and was asked about nobody).
            for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,})(?:\s+' + NAME_PARTICLE + r')?(?=\s+багш)', coded, re.I):
                given = match.group(1).casefold()
                if sum(1 for full in self.staff.values() if full.split('.', 1)[-1].casefold() == given) > 1:
                    return given[:1].upper() + given[1:] + ' багш'
        return named if named and named.endswith(' багш') and not group else None

    def _inherit(self, parts, seed=None):
        """Later parts that name nobody take the person or thing named before. ``seed``: the visitor's previous
        question — 11/28 (2), the user's test: «Соронзонболд багш гэж хэн бэ?» then «2 дахь өдөр 11 цагийн үед уулзвал
        өрөөндөө байх уу, өрөө нь хаана байдаг вэ, бусад багш нар нь хэн бэ» lost the teacher, because only a short
        whole follow-up took the previous question's person; now every part of a longer one does."""
        result = [seed] if seed else [parts[0]]
        for part in (parts if seed else parts[1:]):
            # 11/25 (the user's example): «… соронзонболд багш чинь хэн бэ? Хэдэн давхарт байдаг вэ? Яаж уулзах
            # вэ?» — a sentence about a room, a meeting, an e-mail or lessons that names nobody is about the
            # person an earlier sentence named, also when two sentences stand between them.
            person = next((found for found in map(self._person, reversed(result)) if found), None)
            bare = strip_context_clause(part).strip()
            if person and not person.endswith(' ангийн багш') and self._named(bare) is None and COLLEAGUES.match(bare):
                result.append(person[:-len(' багш')] + ' багшийн тэнхимийн бусад багш нар хэн бэ?')
                continue
            if person and self._named(bare) is None and (PERSON_FOLLOWUP.match(bare) or TIMED_FOLLOWUP.match(bare)):
                if person.endswith(' ангийн багш'):
                    # The class teacher's own room or e-mail, in the wordings the tables read.
                    mail = re.match(r'(?:нь\s+)?(?:и-?мэйл|имэйл|мэйл|цахим|утас|(?:яаж|хэрхэн)\s+холбогд|холбоо\s+бар)', bare, re.I)
                    result.append(person + ('ийн имэйл?' if mail else 'ийн өрөө хаана вэ?'))
                else:
                    result.append(person + ' ' + bare[:1].lower() + bare[1:])
                continue
            if self._named(bare) is None and (PERSON_FOLLOWUP.match(bare) or TIMED_FOLLOWUP.match(bare)):
                # The same after a post or an office («Захирал хэн бэ? Хэдэн давхарт суудаг вэ?»): the follow-up
                # rule reads it against the latest earlier sentence that has a subject.
                anchor = next((earlier for earlier in reversed(result)
                               if self._named(earlier) or self._subject(earlier)), None)
                # «Хэдэн давхарт суудаг вэ?» after a post asks where its holder sits.
                asked = ('хаана суудаг вэ?' if re.match(r'(?:нь\s+)?(?:хэдэн|хэддүгээр|аль|ямар)\s+(?:давхар|өрөө|тоот)', bare, re.I)
                         else bare)
                followup = self._followup(asked, anchor) if anchor else None
                if followup:
                    result.append(followup['rewritten'])
                    continue
            # «…хэн бэ? Уулзах гэсэн юм, хаана суудаг вэ?» (11/23, check set Q32): the reason before a place question is no
            # topic of its own; without it the part asks where the person before is.
            part = strip_context_clause(part)
            subject = self._subject(result[-1])
            if NOT_A_SUBJECT.search(subject):
                subject = ''
            possessive = re.search(r'(?<!\w)нь(?!\w)', part.casefold())
            if (seed and len(result) == 1) or not subject:
                # The thing named before — the previous question or an earlier part — for a part with no subject of its
                # own: «Номын сан хаана байдаг вэ?» then «Хэдэн цагт ажилладаг вэ, хэн ажилладаг вэ» (11/28 (2) sweep:
                # the school's hours and a website search). The follow-up rule keeps its guards (a name, a topic, a
                # room number or the school of its own is a new question).
                anchor = next((earlier for earlier in reversed(result) if self._named(earlier)
                               or (self._subject(earlier) and not NOT_A_SUBJECT.search(self._subject(earlier)))), None)
                followup = (self._followup(part, anchor, max_words=10)
                            if anchor is not None and (possessive or not self._has_topic(part)) else None)
                if followup:
                    result.append(followup['rewritten'])
                    continue
                if seed and len(result) == 1:
                    result.append(part)        # «Сургуулийн хаяг хаана вэ» after a teacher is a question of its own
                    continue
            if subject and (possessive or not self._has_topic(part)):
                # «Захирал хэн бэ, өрөө нь хаана вэ?» (round 20): the later part as a follow-up of the one before
                # («Захирал хаана вэ?»), as when it is asked on its own; one with a topic of its own («…, багш
                # нар хэн бэ?») stays as asked (review).
                followup = self._followup(part, result[-1])
                if followup:
                    result.append(followup['rewritten'])
                    continue
                subject_words = subject.split()
                first = part.split()[0].casefold() if part.split() else ''
                if subject_words and first[:4] == subject_words[-1].casefold()[:4]:
                    subject_words = subject_words[:-1]     # "КУ-2 анги" + "ангийн багш" -> "КУ-2 ангийн багш"
                part = ' '.join(subject_words + [part])
            result.append(part)
        return result[1:] if seed else result

    def _class_group(self, text):
        course = COURSE.search(text)
        # «Механик инженерт 2-р курст шилжин орвол …» asks about the transfer into the 2nd year, an
        # admission question, not class МИ-2 (round 10: W04-A06 lost its stored answer).
        if not course or re.search(r'шилж|элс', text, re.I):
            return text, None
        before = text[:course.start()]
        tokens = list(re.finditer(r'[А-ЯӨҮЁа-яөүё]+', before))
        for token in reversed(tokens[-4:]):
            group = self.groups.get((_stem(token.group()), course.group(1)))
            if group:
                rest = text[course.end():]
                label = group if re.match(r'\s*анги', rest, re.I) else group + ' анги'
                return text[:token.start()] + label + rest, dict(rule='class_group', text=text[token.start():course.end()],
                                                               value=group)
        return text, None

    def _known_group(self, text):
        match = GROUP.search(text)
        known = self.class_names or set(self.groups.values())
        return match.group(1) if match and match.group(1) in known else None

    def _class_contact(self, text):
        group = self._known_group(text)
        if not group or not re.search(r'багш', text, re.I) or not (CONTACT.search(text) or PHONE.search(text)):
            return text, None
        # A phone question keeps its own wording: the reply says phones are not shown, then gives
        # the school e-mail, as the reception desk does.
        canonical = group + (' ангийн багшийн утас?' if PHONE.search(text) else ' ангийн багшийн имэйл?')
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _class_day(self, text):
        group, day = self._known_group(text), WEEKDAY.search(text)
        # 11/25: «КУ-5 анги өнөөдөр хаана хичээлтэй вэ?», «КУ-5 анги одоо хаана байна вэ?» were refused as a question
        # about today's state; the stored timetable answers them with that day's lessons and rooms.
        today = None if day else re.search(r'(?<!\w)(өнөөдөр|маргааш|одоо)(?!\w)', text, re.I)
        # «КУ-2 ангийн багш даваа гарагт хичээлтэй юу?» asks about the teacher, not the class.
        if (not group or not (day or today) or re.search(r'багш', text, re.I)
                or not re.search(r'хичээл|цаг' + ('|хаана|хуваарь' if today else ''), text, re.I)):
            return text, None
        if today and today.group(1).casefold() == 'одоо':
            # «КУ-2 анги одоо хаана байна вэ?»: the lesson in progress and the next one (code review 11/25).
            if not re.search(r'хичээл|хаана', text, re.I):
                return text, None
            canonical = group + ' анги одоо хаана хичээлтэй вэ?'
        elif today:
            canonical = group + ' анги ' + today.group(1).casefold() + ' хэдэн цагт хичээлтэй вэ?'
        else:
            canonical = group + ' анги ' + day.group(1).casefold() + ' гарагт хэдэн цагт хичээлтэй вэ?'
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _class_intent(self, text):
        group = self._known_group(text)
        if not group or TIME_WORDS.search(text):
            return text, None
        if re.search(r'багш', text, re.I) and re.search(r'(?<!\w)хэн(?!\w)', text, re.I):
            canonical = group + ' ангийн багш хэн бэ?'
        elif re.search(r'ангийн\s+багш', text, re.I) and LOCATION.search(text) and not re.search(r'хичээллэ', text, re.I):
            # «КУ-2 ангийн багшийн өрөө хаана вэ?» asks where the class teacher sits, not where the
            # class meets (round 9).
            canonical = group + ' ангийн багшийн өрөө хаана вэ?'
        elif LOCATION.search(text):
            canonical = group + ' анги хаана хичээллэдэг вэ?'
        else:
            return text, None
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _office(self, text):
        match = OFFICE_QUESTION.fullmatch(text.strip())
        if not match or not self.offices:
            return text, None
        # «Сургалтын албаны өрөө хаана вэ» asks where the office is: drop the room word.
        name = re.sub(r'\s+өрөө(?:нд|ний)?$', '', match.group(1).strip(' ,'), flags=re.I)
        lowered = name.casefold()
        if any(lowered in office.casefold() for office in self.offices):
            return text, None
        # Any form of «сургууль» names the school, not the office.
        stems = {stem for stem in (_office_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', name))
                 if not stem.startswith('сургуул')}
        if not stems:
            return text, None
        hits = [office for office in self.offices
                if stems <= {_office_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', office)}]
        if len(hits) != 1:
            return text, None
        short = hits[0].rsplit(',', 1)[-1].strip()
        if sum(short.casefold() in office.casefold() for office in self.offices) != 1:
            return text, None
        replaced = short[:1].upper() + short[1:] + ' ' + match.group(2) + match.group(3)
        return replaced, dict(rule='office_name', text=name, value=short)

    def _class_code(self, text):
        """«ку-2», «КУ2», «ку 2 анги» -> «КУ-2» when that class is in the table (round 8); a spaced
        code only right before «анги», so «Би 2 давхарт …» keeps its pronoun."""
        def code(match):
            digit = match.group(2) or match.group(3) or str(SPOKEN_DIGITS.get((match.group(4) or '').casefold(), ''))
            value = match.group(1).upper() + '-' + digit
            return value if digit and value in self.class_names else match.group(0)
        # «КУ хоёр анги» (speech writes the number as a word), round 13.
        fixed = re.sub(r'(?<![\w-])([А-ЯӨҮЁа-яөүё]{2})(?:-?(\d)(?![\w-])|\s+(\d)(?=\s+анги)|\s+(' + '|'.join(SPOKEN_DIGITS)
                       + r')(?=\s+анги))', code, text, flags=re.I)
        return (fixed, dict(rule='class_code', text=text, value=fixed)) if fixed != text else (text, None)

    @staticmethod
    def _desk_wording(text):
        """«604 тоотод хэн суудаг вэ?», «Програмчлал хэн заадаг вэ?», «Оюутны албаны хүн хэн бэ?» in the wordings
        the tables read (the room's card, the subject's teachers, the office's staff)."""
        stripped = text.strip()
        room = re.fullmatch(r'([A-Za-zА-ЯӨҮЁа-яөүё]?\d{2,4}[A-Za-zА-ЯӨҮЁа-яөүё]?)\s*(?:тоот(?:од|\s+өрөөнд)?|өрөөнд)\s+'
                            r'(?:хэн|юу|хэний\s+өрөө|хэн\s+хэн)\s*(?:суудаг|байдаг|ажилладаг|байна|байгаа)?\s*(?:вэ|бэ)?\s*\??',
                            stripped, re.I)
        if room:
            return room.group(1) + ' тоот хаана вэ?', dict(rule='desk_wording', text=text, value='room')
        head = re.fullmatch(r'(.{2,60}?тэнхимийн\s+эрхлэгч)\s+(?:нь\s+)?(?:хаана\s+(?:суудаг|байдаг|байна|байрладаг)|'
                            r'(?:хэдэн|хэддүгээр|аль)\s+(?:давхар|өрөө|тоот)\w*(?:\s+(?:суудаг|байдаг|байна))?)\s*(?:вэ|бэ)?\s*\??',
                            stripped, re.I)
        if head:
            return head.group(1) + 'тэй яаж уулзах вэ?', dict(rule='desk_wording', text=text, value='department_head')
        subject = re.fullmatch(r'(.{2,40}?)(?:ийг|ыг|г)?\s+хэн\s+(?:заадаг|ордог|заах)\s+(?:вэ|бэ)\s*\??', stripped, re.I)
        if subject and not re.search(r'хичээл|(?<!\w)анги|тэнхим', subject.group(1), re.I):
            return subject.group(1) + ' хичээлийг хэн заадаг вэ?', dict(rule='desk_wording', text=text, value='subject')
        office = re.fullmatch(r'(.{2,60}?(?:алба|төв|сан|хэлтэс))(?:ны|ний|гийн|ийн|ын)\s+(?:хүн|хүмүүс|ажилчид|ажилтнууд|'
                              r'мэргэжилтнүүд)(?:\s+нь)?\s+хэн(?:\s+хэн)?\s+(?:бэ|вэ)\s*\??', stripped, re.I)
        if office is None:
            office = re.fullmatch(r'(.{2,60}?(?:алба|төв|сан|хэлтэс))(?:нд|д|т)\s+хэн(?:\s+хэн)?\s+'
                                  r'(?:ажилладаг|байдаг|суудаг)\s+(?:вэ|бэ)\s*\??', stripped, re.I)
        if office:
            name = office.group(1)
            suffix = 'гийн' if name.endswith('сан') else ('ийн' if name.endswith(('төв', 'хэлтэс')) else 'ны')
            return name + suffix + ' ажилтан хэн бэ?', dict(rule='desk_wording', text=text, value='office_staff')
        return text, None

    def _unvowelled(self, text):
        """«сургалтын тлбр хэд вэ» -> «сургалтын төлбөр хэд вэ» (typing without vowels, 2026-11-26)."""
        def restore(match):
            word = match.group(0)
            plain = word.casefold()
            # An all upper-case word is an abbreviation («ШМТК»); a capital first letter starts a sentence («Тлбр»).
            if (word.isupper() or len(word) < 3 or plain in self.known_words
                    or any(letter in VOWELS for letter in plain[1:])):
                return word
            restored = self.vowelless.get(skeleton(plain))
            if restored is None:
                return word
            return restored[:1].upper() + restored[1:] if word[:1].isupper() else restored
        changed = re.sub(r'(?<![\w.-])[а-яөүёА-ЯӨҮЁ]+(?![\w.-])', restore, text)
        return (changed, dict(rule='vowelless_typing', text=text, value=changed)) if changed != text else (text, None)

    @staticmethod
    def _department_head(text):
        """«цахилгааны тэнхимийн эрхлэгч» -> «Цахилгаан электроникийн инженерийн тэнхимийн эрхлэгч»."""
        changed = DEPARTMENT_HEAD.sub(DEPARTMENT_HEAD_NAME, text)
        # 11/26 (7): «сургуулийн дарга» is the school's «захирал» (the recorded post).
        def head(match):
            word = SCHOOL_HEAD_FORMS[(match.group(1) or '').casefold() or None]
            return word[:1].upper() + word[1:] if match.group(0)[:1].isupper() else word
        changed = SCHOOL_HEAD.sub(head, changed)
        return (changed, dict(rule='department_head', text=text, value=changed)) if changed != text else (text, None)

    def _everyday(self, text, sentences_only=False):
        """The question an everyday wording of a whole sentence means, or None (2026-11-26). ``sentences_only``: the
        sentence patterns alone — no one-word topic, room, office or department reading."""
        plain = ' '.join(re.sub(r'[?!.,;]+', ' ', text or '').casefold().split())
        if not plain or len(plain) > 120:
            return None
        if plain in TOPIC_WORDS and not sentences_only:
            return TOPIC_WORDS[plain]
        about = ABOUT_WISH.fullmatch(plain)
        if about:
            topic = TOPIC_GENITIVE.get(about.group('topic'), about.group('topic'))
            if topic in TOPIC_WORDS:
                return TOPIC_WORDS[topic]
        for pattern, question in EVERYDAY_QUESTIONS:
            if pattern.fullmatch(plain):
                return question
        if sentences_only:
            return None
        about = DEPARTMENT_ABOUT.fullmatch(plain)
        if about:
            return next(intro for stem, intro in DEPARTMENT_INTRO if about.group(1).startswith(stem))
        room = BARE_ROOM.fullmatch(plain)
        if room and room.group(1) in self.rooms:
            return self.rooms[room.group(1)] + ' тоот хаана вэ?'
        if FOREIGN_OFFICE.fullmatch(plain):
            office = next((name for name in self.offices if 'гадаад харилцаа' in name.casefold()), None)
            if office:
                return office + ' хаана байдаг вэ?'
        exists = EXISTS_ASK.fullmatch(plain)
        if exists:
            office = next((name for name in self.offices if name.casefold() == exists.group(1)), None)
            if office:
                return office + ' хаана байдаг вэ?'
        return None

    def _post_subject(self, text):
        """«захирал маргааш 10 цагт завтай юу» -> «Т.Оюунжаргал багш маргааш 10 цагт завтай юу» (2026-11-26 (7)): a post
        one person holds, asked about a day, an hour, now or being in, is that person asked by name. A post several
        people hold stays as asked: the tables list them."""
        found = self.posts(text) if self.posts else None
        if not found or len(found[0]) != 1:
            return text, None
        people, together, rest = found[:3]
        full = people[0].name
        if re.sub(r'\s+', '', full.casefold()) not in self.staff:
            return text, None
        # «сэтгэл зүйч одоо хаана байна вэ»: the name wording has no particle («… багш одоо хаана байна»).
        canonical = full + ' багш' + ('тай ' if together else ' ') + rest
        return canonical, dict(rule='post_holder', text=text, value=canonical)

    def _staff_name(self, text):
        # A given name typed in lower case («сэлмаа багш») is the same teacher (round 8); only names in
        # the staff table are read, so ordinary words before «багш» are not.
        for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,})(?:\s+' + NAME_PARTICLE + r')?(?=\s+багш)', text, re.I):
            full = self.given_names.get(match.group(1).casefold())
            if full:
                # «соронзонболд гэдэг багш» is «Н.Соронзонболд багш»: the word between goes with the given name.
                return text[:match.start()] + full + text[match.end():], dict(rule='staff_name',
                    text=match.group(1), value=full)
        # «Сэлмаагийн өрөө хаана вэ?» (a given name in the genitive, round 13) is that teacher's office.
        for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,}?)(?:гийн|ийн|ын)(?=\s+(?:өрөө|ажлын\s+өрөө|имэйл))',
                                 text, re.I):
            full = self.given_names.get(match.group(1).casefold())
            if full:
                return (text[:match.start()] + full + ' багшийн' + text[match.end():],
                        dict(rule='staff_name', text=match.group(0), value=full))
        # 11/25: «Оюунжаргал захирал хаана суудаг вэ?» (the post instead of «багш»), and a given name followed by a
        # question about a person («Оюунжаргал хаана суудаг вэ?», «Хандсүрэнтэй яаж уулзах вэ?»).
        match = re.match(r'\s*([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,}?)(?:(тай|тэй|той)|\s+' + POST_WORD + r'(тай|тэй|той)?)?\s+(\S.*)$', text, re.I)
        full = self.given_names.get(match.group(1).casefold()) if match else None
        if full and (PERSON_FOLLOWUP.match(match.group(4)) or MEET_ASK.match(match.group(4))):
            with_them = 'тай' if (match.group(2) or match.group(3)) else ''
            return (full + ' багш' + with_them + ' ' + match.group(4),
                    dict(rule='staff_name', text=match.group(1), value=full))
        # 11/25: «Оюунжаргал гэж хэн бэ?», «Хандсүрэн гэдэг хүн хэн бэ?» or the given name alone asks who the
        # person is; a staff member who is no teacher is named without «багш».
        match = re.fullmatch(r'\s*([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,})(?:\s+(?:гэж|гэдэг\s+хүн|гэдэг\s+багш|гэдэг|гуай))?'
                             r'(?:\s+(?:чинь|маань))?(?:\s+хэн\s+(?:бэ|вэ))?\s*[?.!]*\s*', text, re.I)
        full = self.given_names.get(match.group(1).casefold()) if match else None
        if full:
            return full + ' гэж хэн бэ?', dict(rule='staff_name', text=match.group(1), value=full)
        return text, None

    @staticmethod
    def _day_wording(full, day):
        word = day.group(1).casefold()
        return full + ' багш ' + (word if word in ('өнөөдөр', 'маргааш') else word + ' гарагт') + ' хичээлтэй юу?'

    def _teacher_intent(self, text):
        match = TEACHER.search(text)
        key = match and (match.group(1) + '.' + match.group(2)).casefold()
        if not match or key not in self.staff:
            return text, None
        full = self.staff[key]
        # Day and time words are looked for outside the teacher's own name («Г.Баасан», «А.Даваа»).
        rest = text[:match.start()] + ' ' + text[match.end():]
        # 11/26: a day or an hour with a lesson / free-time word is answered from the timetable for that time. The
        # tables' own parser decides (one rule for both, code review); the name goes first, every other word stays.
        said = re.sub(r'^[а-яөүё]*', '', text[match.end():], flags=re.I)        # «багш|тай», «багш|ийн», «багш|аас»
        others = ' '.join((text[:match.start()] + ' ' + said).split())
        if teacher_asked_now(others):               # «яг одоо хаана байгаа вэ»: the timetable at this minute
            canonical = full + ' багш одоо хаана байна'
            return (canonical, dict(rule='teacher_time', text=text, value=canonical)) if canonical != text else (text, None)
        if teacher_time_parts(others) is not None:
            canonical = full + ' багш ' + others
            return (canonical, dict(rule='teacher_time', text=text, value=canonical)) if canonical != text else (text, None)
        day = DAY_WORD.search(rest)
        other_time = OTHER_TIME.search(rest)
        # Already the closed wording (e.g. «…багшийн имэйл юу вэ?»): leave it as asked.
        # «…багш хаана (байна) вэ?» is the timetable-status wording; it must not become an office room.
        if re.search(r'багшийн\s+(?:и-?мэйл|имэйл|мэйл|цахим\s+шуудан|утас)|багшийн\s+өрөө\s+хаана\s+вэ|'
                     r'багш\s+одоо\s+хичээлтэй\s+юу|багш\s+хэзээ\s+оюутантай\s+уулздаг|'
                     r'багш\s+(?:одоо\s+)?хаана(?:\s+байна)?\s*(?:вэ)?\s*\??$', text, re.I):
            return text, None
        # «… багш чинь хэн бэ?», «… багш маань хаана суудаг вэ?»: the particle after «багш» changes nothing.
        after = re.sub(r'^(?:\s+' + NAME_PARTICLE + r')+(?=\s)', '', text[match.end():], flags=re.I)
        if WHO.match(after) and not re.search(r'ангийн\s+багш|зураг', text, re.I):
            # 11/25: «Соронзонболд багш гэж хэн бэ хаана байдаг вэ» asks who the teacher is; that answer holds the
            # room, the e-mail and the lessons too, so the room question after it is not asked separately.
            canonical = full + ' багш гэж хэн бэ?'
        elif OWN_CLASS_ASK.search(after):
            canonical = full + ' багш гэж хэн бэ?'       # the card names the class the teacher is in charge of
        elif LESSON_TIME_ASK.search(rest) and not day and not other_time_but_clock(rest):
            canonical = full + ' багш өнөөдөр хичээлтэй юу?'
        elif LESSON_ROOM_ASK.search(rest) and not day:
            canonical = full + ' багш өнөөдөр хаана хичээл заах вэ?'
        elif ((MEET_ASK.search(rest) or IN_ASK.fullmatch(others.rstrip('?？.! '))) and not day and not PHONE.search(text)
              and not CONTACT.search(text) and not re.search(r'хичээлтэй|\d{1,2}:\d{2}', rest, re.I)):
            # «… багштай яаж уулзах вэ?», «… багшийг хайж байна», «… багш одоо өрөөндөө байгаа юу?»: where the
            # teacher sits, what the timetable says now, and how to arrange a meeting.
            canonical = full + ' багштай яаж уулзах вэ?'
        elif PHONE.search(text):
            # «холбоо барих утас»: phones are never shown; the phone wording says so and gives
            # the school e-mail instead (not a silent e-mail answer).
            canonical = full + ' багшийн утас?'
        elif CONTACT.search(text):
            canonical = full + ' багшийн имэйл?'
        elif ROOM_ASK.search(text):
            # «…багш даваа гарагт хаана байна вэ?» asks where the teacher is then: that day's
            # timetable (11/17 (5)), not the office room; a clock time has no wording, so it stays.
            if (day or other_time) and not re.search(r'өрөө|тоот', text, re.I):
                if not day:
                    return text, None
                canonical = self._day_wording(full, day)
            else:
                canonical = full + ' багшийн өрөө хаана вэ?'
        elif MEETING.search(text):
            if re.search(r'(?<!\w)хэзээ(?!\w)', text, re.I):
                # «хэзээ уулзах» asks for office hours; «хэзээ хичээлтэй» asks for the teacher's
                # timetable, which has no closed wording here, so it stays as asked.
                if not re.search(r'уулз|чөлөөтэй|(?<!\w)сул(?!\w)', text, re.I):
                    return text, None
                canonical = full + ' багш хэзээ оюутантай уулздаг вэ?'
            elif day:
                # «маргааш», «өнөөдөр» or a weekday is not «now»: that day's timetable wording.
                canonical = self._day_wording(full, day)
            elif other_time:
                # A clock time has no closed wording: leave the question as asked.
                return text, None
            else:
                canonical = full + ' багш одоо хичээлтэй юу?'
        else:
            return text, None
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='teacher_intent', text=text, value=canonical)

    def _named(self, text):
        """The thing a question names — a teacher («Б.Сэлмаа багш»), a class group («КУ-2 анги»)
        or a recorded office («Номын сан») — or None."""
        teacher = TEACHER.search(text)
        if teacher:
            return teacher.group(1).upper() + '.' + teacher.group(2) + ' багш'
        if self.staff_names:
            _, rewrite = self._staff_name(text)
            if rewrite:
                return rewrite['value'] + ' багш'
        group = GROUP.search(text)
        if group:
            return group.group(1) + ' анги'
        lowered = text.casefold()
        for office in self.offices:
            short = office.rsplit(',', 1)[-1].strip()
            if short and short.casefold() in lowered:
                return short
        return None

    # 11/28 (6) sweep: «оюутны алба руу яаж очих вэ», «сургалтын албаны өрөөний дугаар хэд вэ», «эмнэлэг хаана байдаг вэ».
    _OFFICE_PLACE = re.compile(r'\s*(?P<office>.{2,60}?)(?:(?P<to>\s+(?:руу|рүү|луу|лүү))\s+(?:яаж|хэрхэн)\s+(?:очих|явах|орох)'
                               r'|(?P<gen>гийн|ийн|ний|ны|ын)\s+(?:өрөөний\s+дугаар\s+(?:хэд|хэдэн)|өрөө\s+(?:хэдэн|хэддүгээр)\s+тоот|'
                               r'өрөө\s+хаана(?:\s+(?:байдаг|байна))?))\s+(?:вэ|бэ)\s*[?？.!]*\s*', re.I)

    def _office_place(self, text):
        """«<алба> хаана байдаг вэ?» for a recorded office asked the way to or its room number; None otherwise."""
        if re.fullmatch(r'\s*эмнэлэг(?:ийн\s+өрөө)?\s+хаана(?:\s+(?:байдаг|байна))?\s+(?:вэ|бэ)\s*[?？.!]*\s*', text, re.I):
            return 'Эмч хаана байдаг вэ?'
        asked = self._OFFICE_PLACE.fullmatch(text)
        if not asked:
            return None
        said = asked['office'].strip().casefold()
        for office in self.offices:
            name = office.rsplit(',', 1)[-1].strip()
            if name and name.casefold() == said:
                return name + ' хаана байдаг вэ?'
        return None

    def _statement_about(self, original, text):
        """The class, teacher or office a sentence with no question names («хүүхэд маань КУ-2 ангид сурдаг», «Сэлмаа
        багш манай ангийн багш»), or None. A request («… харуулаач», «… өгнө үү»), a wish to meet or to get a paper, and a
        greeting or thanks are no such sentence."""
        # A greeting said without a comma («сайн байна уу хүүхэд маань …») is no question; a bare name («Номын сан», «КУ-2»)
        # keeps its own card.
        said = re.sub(r'^\s*сайн\s+(?:байна|байцгаана)\s+уу\s*[,!.?？]*\s*', '', (original or '').strip(), flags=re.I)
        if (len(said.split()) < 3 or '?' in said or '？' in said or QUESTION_WORD.search(said) or MEET_ASK.search(said)
                or REQUEST.fullmatch(text.strip()) or GREETING.fullmatch(said.casefold().strip(' !.'))
                or re.search(r'(?:аач|ээч|ооч|өөч|аарай|ээрэй|оорой|өөрэй|(?<!\w)өгнө|(?<!\w)хэлнэ|харуул\w*|'
                             r'мэдмээр|мэдэх\s+гэсэн|асуух\s+гэсэн|асуумаар|гэсэн\s+юм|байх\s+ёстой|'
                             # a wish or a thing asked for: «… холбогдмоор байна», «… хуваарь авмаар байна», «… багшийн имэйл»
                             r'маар|моор|мөөр|хүс|хэрэгтэй|имэйл|имейл|мэйл|майл|утас|утсы|өрөө|давхар|хуваар|хичээл|цаг|хаяг|тоот|байршил|'
                             # «… зурагтай танилцуулгыг үзье» (a request in the first person: -ъя, -ье, -ъё, -ая)
                             r'зураг|танилцуул|\w(?:ъя|ье|ъё|ая|оё|ёё)(?!\w))',
                             said, re.I)):
            return None
        coded = self._class_code(text)[0]
        group = GROUP.search(coded)
        if group:
            return group.group(1) + ' анги'
        person = self._person(coded)
        if person:
            return person
        named = self._named(coded)
        return named or None

    def _followup(self, query, previous, max_words=6):
        """«Номын сан хаана вэ?» then «Хэдэн цагт ажилладаг вэ?» (round 4, 11/17): an elliptical
        follow-up takes only the previous question's named thing — a teacher, class, office or
        its short subject — never the whole history, which hurts retrieval (Lin et al. 2021;
        Voskarides et al. 2020). A question with a topic or a name of its own is a new question
        (a topic shift) and is left as asked; so is a greeting."""
        text = query.strip()
        lowered = text.casefold()
        if (not isinstance(previous, str) or not previous.strip() or len(_words(text)) > max_words
                or not (QUESTION_WORD.search(text) or re.search(r'(?<!\w)нь\s*\?*$', lowered))
                or GREETING.fullmatch(lowered.strip(' ?!.'))
                or GROUP.search(self._class_code(text)[0]) or self._named(text) is not None
                or (any(keyword in lowered for keyword in self.topic_keywords if keyword not in FOLLOWUP_ATTRIBUTES)
                    and not OWN_ATTRIBUTE.match(lowered))):
            return None
        previous = self._class_code(previous.strip())[0]
        entity = self._named(previous)
        if entity is None:
            subject = self._subject(previous)
            if not subject or len(subject.split()) > 4 or QUESTION_WORD.search(subject) or NOT_A_SUBJECT.search(subject):
                return None
            entity = subject
            # «Механик тэнхимийн багш нар хэн бэ?» then «Эрхлэгч нь хэн бэ?»: the department is the thing (11/28 (3)).
            unit = re.fullmatch(r'(.+?)\s+тэнхим(?:ийн)?(?:\s+(?:багш(?:\s*нар\w*)?|ажилтн\w*|бусад\s+багш\s*нар\w*))?', entity, re.I)
            if unit:
                entity = unit.group(1) + ' тэнхим'
        # «тэнд» (there) points at the previous thing, which takes its place (round 13); «энд» (here) is
        # the school itself and starts a new question (review). So does a room number or the school by name
        # («604 тоот хаана байдаг вэ», «Сургуулийн хаяг хаана вэ» after a teacher, 11/28 (2) sweep).
        if (re.search(r'(?<!\w)энд(?!\w)', text, re.I) or re.search(r'(?<!\w)(?:сургуул|коллеж|шмтк)', text, re.I)
                or re.search(r'(?<![\w-])[0-9]{3,4}(?:\s*(?:тоот|тоотод|тоотын|-?р\s+өрөө))?(?!\w)', text, re.I)):
            return None
        rest = re.sub(r'\s+(?=[?!.])', '', re.sub(r'(?<!\w)(?:нь|тэнд)(?!\w)\s*', '', text, flags=re.I)).strip()
        # «Түүнтэй уулзаж болох уу?» (round 20): «түүнтэй» (with them) is the thing just named, which then takes
        # «-тай» whatever follows («Одоо түүнтэй …», «Түүнтэй утсаар холбогдож болох уу?», review).
        with_them = bool(re.search(r'(?<!\w)(?:түүнтэй|тэр\s+хүнтэй)(?!\w)', rest, re.I))
        rest = re.sub(r'\s*(?<!\w)(?:түүнтэй|тэр\s+хүнтэй)(?!\w)\s*', ' ', rest, flags=re.I).strip()
        rest = rest[:1].lower() + rest[1:]
        group = GROUP.search(previous)
        if (group and entity == group.group(1) + ' анги' and re.match(r'\s+ангийн\s+багш', previous[group.end():])
                and (with_them or re.match(r'(?:и-?мэйл|имэйл|мэйл|цахим|өрөө|утас|утсан|байршил|давхар)', rest.casefold()))):
            # «КУ-2 ангийн багш хэн бэ?» then «Өрөө нь хаана вэ?» / «Имэйл нь?» (round 9): the class
            # teacher's room or e-mail, not the class's own room.
            entity = group.group(1) + ' ангийн багш'
        head = entity.split()
        # «Өрөө нь?», «Давхар нь?» alone (round 8): the whole location question about the thing.
        bare = re.fullmatch(r'(өрөө|байршил|давхар)(?:\s+(?:хаана|хэд|хэдэн|хэддүгээр|юу)(?:\s+(?:вэ|бэ))?)?\s*\??',
                            rest.casefold())
        if bare:
            if head[-1] == 'багш':
                # A teacher's room and floor are both in the recorded office.
                rewritten = ' '.join(head[:-1] + ['багшийн']) + ' өрөө хаана вэ?'
            elif bare.group(1) == 'давхар':
                rewritten = entity + ' хэддүгээр давхарт вэ?'
            else:
                rewritten = entity + ' хаана вэ?'
            return dict(rule='followup_context', previous=previous, entity=entity, rewritten=rewritten)
        first = rest.split()[0].casefold() if rest.split() else ''
        if len(head) > 1 and first[:4] == head[-1].casefold()[:4]:
            head = head[:-1]      # «КУ-2 анги» + «ангийн багш хэн бэ» -> «КУ-2 ангийн багш хэн бэ»
        elif head[-1].casefold() == 'багш' and re.match(r'(?:и-?мэйл|имэйл|мэйл|цахим|өрөө|утас|утсан)', first):
            head = head[:-1] + ['багшийн']   # -> «Б.Сэлмаа багшийн имэйл юу вэ»
        elif head[-1].casefold() == 'тэнхим' and re.match(r'(?:эрхлэгч|багш|и-?мэйл|имэйл|утас)', first):
            head = head[:-1] + ['тэнхимийн']   # round 12: -> «Механик тэнхимийн эрхлэгч хэн бэ»
        elif ((with_them or re.match(r'(?:(?:яаж|хэрхэн|одоо|өнөөдөр|маргааш)\s+)?(?:уулз|холбогд)', rest.casefold())
                and not re.search(r'утас|утсан|и-?мэйл|имэйл|мэйл|хаяг|дугаар', rest.casefold()))
                and head[-1].casefold() != 'анги' and not re.search(r'(?:тай|тэй|той)$', head[-1].casefold())):
            # «Сэтгэл зүйч хаана суудаг вэ?» then «Уулзаж болох уу?» (round 16): one meets or contacts
            # someone «-тай»: «Сэтгэл зүйчтэй уулзаж болох уу?», the wording the desk's lookup reads.
            head = head[:-1] + [_comitative(head[-1])]
        return dict(rule='followup_context', previous=previous, entity=entity, rewritten=' '.join(head + [rest]))

    def plan(self, query, previous=None):
        """Return parts to route; each keeps the visitor's original wording for the reply.
        ``previous``: the visitor's previous question, for an elliptical follow-up."""
        # Round 21: a spoken question's filler and colloquial ending first («тэгээд захирал хэн юм бэ»), so the
        # follow-up and split rules below read «захирал хэн бэ».
        stripped = spoken_form(_without_courtesy(strip_fillers(query))[0])
        # The previous question's opening is no subject either («Сайн байна уу, сэтгэл зүйч хаана суудаг вэ?»), review.
        previous = spoken_form(_without_courtesy(strip_fillers(previous))[0]) if previous else previous
        followup = (self._followup(stripped, previous)
                    if previous and not (COLLEAGUES.match(stripped.strip()) and self._person(previous))
                    and not WHO_TO_ASK.fullmatch(stripped)
                    and not (self.split_compound and len(self._split(stripped)) > 1) else None)
        if previous and WHO_TO_ASK.fullmatch(stripped) and self._named(stripped) is None:
            # Who to go to about what was just asked: the person named before, or the office of the previous question's topic.
            person = self._person(previous)
            rewritten = (person + 'тай яаж уулзах вэ?' if person
                         else previous.strip().rstrip(' ?？.!') + ' — энэ талаар хэнд хандах вэ?')
            followup = dict(rule='who_to_ask', previous=previous, entity=person, rewritten=rewritten)
        asked = followup['rewritten'] if followup else stripped
        # «… — энэ талаар хэнд хандах вэ?» carries the previous question's words as its topic: one question, not split.
        originals = (self._split(asked) if self.split_compound and not (followup and followup['rule'] == 'who_to_ask')
                     else [asked.strip()])
        routed = list(originals)
        # The previous question's person or thing for a follow-up too long for the rule above (11/28 (2)); a
        # message that names someone or something of its own starts afresh.
        seed = (previous if previous and not followup and self._named(stripped) is None
                and (self._person(previous) or self._named(previous)
                     or (self._subject(previous) and len(self._subject(previous).split()) <= 4
                         and not NOT_A_SUBJECT.search(self._subject(previous)))) else None)
        if len(originals) > 1:
            # Distributed parallel parts already carry the subject; others may inherit it.
            distributed = self._distribute(originals)
            routed = distributed if distributed != originals else self._inherit(originals, seed)
        elif seed:
            routed = self._inherit(originals, seed)
        parts = []
        for original, text in zip(originals, routed):
            rewrites = []
            normalized = normalize_wording(text)
            if normalized != text:
                rewrites.append(dict(rule='wording', text=text, value=normalized))
                text = normalized
            if self.enabled:
                # 11/26: typing without vowels, a department head by its short name, then an everyday wording of
                # the whole sentence («энэ яадаг сургууль вэ», «төлбөр», «604 хаана байдаг вэ»).
                for rule in (self._unvowelled, self._department_head):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
                # Also the part's own words when the subject it inherited is the school itself («сургуульд энд
                # сурснаар …», the user's test, 11/26). Any other inherited subject stays: «Дотуур байр байдаг уу?
                # Орохдоо юу бүрдүүлэх вэ?» asks about the dormitory (code review 11/26).
                everyday = self._everyday(text)
                if everyday is None and text != original and len(original.split()) >= 3:
                    own = set(_words(original))
                    added = [word for word in _words(text) if word not in own]
                    if added and all(word.startswith(('сургуул', 'коллеж', 'шмтк')) for word in added):
                        everyday = self._everyday(normalize_wording(original), sentences_only=True)
                if everyday is not None:
                    rewrites.append(dict(rule='everyday_wording', text=text, value=everyday))
                    parts.append(dict(original=original, query=everyday, rewrites=rewrites))
                    continue
            # «Сургуулийн тодорхойлолт авах гэсэн юм» (round 9): at the desk, a wish to get a paper
            # asks where it is issued.
            wish = REQUEST.fullmatch(text.strip())
            if wish and not QUESTION_WORD.search(wish.group(1)):
                rewrites.append(dict(rule='request', text=text, value=wish.group(1) + ' хаанаас авах вэ?'))
                text = wish.group(1) + ' хаанаас авах вэ?'
            # 11/28 (4), the user: «хүүхэд маань КУ-2 ангид сурдаг» (no question) got «тодруулна уу»; asking back is right, but
            # ask what the visitor wants to know about the thing they named.
            about = self._statement_about(original, text) if len(originals) == 1 else None
            if about:
                rewrites.append(dict(rule='statement_about', text=text, value=about))
                parts.append(dict(original=original, query=about + ' — юу мэдэх вэ?', rewrites=rewrites))
                continue
            if self.class_groups:
                for rule in (self._class_code, self._class_group, self._class_contact, self._class_day, self._class_intent,
                             self._office):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
                # 11/28 (6) sweep: «ку2 ийн хуваарь» — the ending written apart from the class code.
                joined = re.sub(r'([А-ЯӨҮЁ]{2}-\d)\s+(?:ийн|ын|ний)(?!\w)', r'\1 ангийн', text)
                if joined != text:
                    rewrites.append(dict(rule='class_ending', text=text, value=joined))
                    text = joined
            office_place = self._office_place(text)
            if office_place:
                rewrites.append(dict(rule='office_place', text=text, value=office_place))
                text = office_place
            if self.staff_names:
                for rule in (self._post_subject, self._staff_name, self._teacher_intent, self._desk_wording):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
            parts.append(dict(original=original, query=text, rewrites=rewrites))
        # 11/25: «… багш гэж хэн бэ, хаана суудаг вэ?» — the answer to who a person is already holds the room, the
        # e-mail and the lessons, so a later part about the same person is not answered a second time.
        # Only what that answer holds (room, e-mail, subjects): a part about another day, a phone or a meeting is
        # still asked, and names are compared whole (code review 11/25).
        described = {match.group(1).replace(' ', '').casefold() for part in parts
                     for match in [PERSON_CARD.fullmatch(part['query'].strip())] if match}
        if described and len(parts) > 1:
            covered = [PERSON_COVERED.match(part['query'].strip()) for part in parts]
            kept = []
            for part, match in zip(parts, covered):
                name = match.group(1).replace(' ', '').casefold() if match else None
                if name in described:
                    # Answered by the card: shown as one of the questions above it, not dropped from the reply.
                    card = next(item for item in parts if (PERSON_CARD.fullmatch(item['query'].strip()) or [None, ''])[1]
                                .replace(' ', '').casefold() == name)
                    if card is not part and part['original'].strip() not in card['original']:
                        card['original'] = card['original'].strip() + ' ' + part['original'].strip()
                    continue
                kept.append(part)
            parts = kept
        result = dict(enabled=self.enabled, compound=len(parts) > 1, parts=parts,
                      changed=len(parts) > 1 or any(p['query'] != query.strip() for p in parts))
        if followup:
            result['followup'] = followup
        return result


def context_for(result, plan=None):
    """The question the visitor's next elliptical question («Хэдэн давхарт байдаг вэ?», «Тэр хүнтэй яаж уулзах вэ?») refers
    to. 11/28 (3), the user's long chat: after «хэнд хандах вэ» → «Сургалтын алба» the next «хэдэн давхарт» knew nothing of the
    office, and after a question of three parts the page sent all three. The office named in a referral answer, else the
    last part as the planner read it; None keeps the visitor's own question."""
    if result.get('reason_code') == 'referral_office':
        office = ((result.get('referral') or {}).get('office') or '').split(' (')[0].strip()
        if office:
            return office + ' хаана байдаг вэ?'
    # An office card answering a question that named the office another way («сургалтын төлбөрөө хаана төлөх вэ» →
    # «Санхүүгийн алба: 8-р давхар …»): the next «хэдэн цагт ажилладаг вэ» is about that office.
    card = re.match(r'(?:\[[^\]]*\]\s*)?([^:\n]{2,60}):\s*\d+-р давхар', str(result.get('answer') or ''))
    if card and result.get('reason_code') == 'reception_service_lookup':
        return card.group(1).strip() + ' хаана байдаг вэ?'
    parts = (plan or {}).get('parts') or []
    if parts and plan.get('changed'):
        # Every part, so «хэнд хандах вэ» still sees the whole topic; the follow-up rules take the thing named first.
        return ' '.join(dict.fromkeys(part['query'].strip() for part in parts))[:300]
    return None


def _source_urls(result):
    urls = []
    for item in (result.get('citations') or []) + (result.get('related_sources') or []):
        url = item.get('source_url_or_filename') or item.get('url')
        if url and url not in urls:
            urls.append(url)
    return urls


def compose(query, plan, results):
    """One reply from per-part results; never merges or rewrites their answer text."""
    answered = [bool((r.get('answer') or '').strip()) for r in results]
    base = deepcopy(results[answered.index(True)] if any(answered) else results[0])
    lines, citations, related, seen = [], [], [], set()
    previous, shown = None, set()
    for part, result, ok in zip(plan['parts'], results, answered):
        asked = part['original'].strip()
        asked = asked[:1].upper() + asked[1:]  # «…, хэсэгчлэн төлж болох уу?» was echoed in lower case
        if ok and previous is not None and result['answer'].strip() == previous:
            # Two parts answered by the same stored answer show it once, under both questions (11/23, Q14).
            header, _, body = lines[-1].partition('\n')
            lines[-1] = header + ' ' + asked + '\n' + body
        elif ok:
            # A line an earlier part already showed (the room, the e-mail, «Хуваарь өөрчлөгдөж болно.») is not
            # shown a second time under the next question (11/25); what is left is that part's own answer.
            fresh = [line for line in result['answer'].strip().split('\n')
                     if not (len(line.strip()) >= 12 and line.strip() in shown)]
            while fresh and not fresh[-1].strip():
                fresh.pop()
            if any(line.strip() for line in fresh):
                lines.append(asked + '\n' + '\n'.join(fresh).strip())
            elif previous is not None:      # everything was said just above: the question joins that block
                header, _, body = lines[-1].partition('\n')
                lines[-1] = header + ' ' + asked + '\n' + body
            else:
                lines.append(asked + '\n' + result['answer'].strip())
            shown.update(line.strip() for line in result['answer'].split('\n'))
        else:
            # The page shows no note under a compound answer, so where to ask goes with the part (11/22).
            where = (result.get('referral') or {}).get('office')
            lines.append(asked + '\nЭнэ талаар мэдээлэл олдсонгүй.' + (' Лавлах газар: ' + where + '.' if where else ''))
        previous = result['answer'].strip() if ok else None
        for item in result.get('citations') or []:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                citations.append(item)
        related += [item for item in result.get('related_sources') or [] if item not in related]
    referral = next((r.get('referral') for r, ok in zip(results, answered) if not ok and r.get('referral')), None)
    base.update(query=query, answer='\n\n'.join(lines) if any(answered) else None,
                citations=citations, related_sources=related[:3], clarification=None,
                route='C' if all(answered) else ('C' if any(answered) else 'E'),
                reason_code='compound_parts_all_answered' if all(answered) else
                            ('compound_parts_partly_answered' if any(answered) else 'compound_parts_not_answered'),
                answer_kind='compound_parts' if any(answered) else None,
                generated=False, llm_calls=sum(r.get('llm_calls', 0) for r in results),
                parts=[dict(original=part['original'], query=part['query'], rewrites=part['rewrites'],
                            route=result.get('route'), reason_code=result.get('reason_code'),
                            answer_kind=result.get('answer_kind'), answered=ok,
                            source_urls=_source_urls(result)[:3], answer_faq_id=result.get('answer_faq_id'),
                            locators=[c.get('locator') for c in result.get('citations') or [] if c.get('locator')][:3])
                       for part, result, ok in zip(plan['parts'], results, answered)])
    base['reason_codes'] = [base['reason_code']]
    if referral:
        base['referral'] = referral
        # Nothing answered: say so before where to ask (11/23, check set Q22, Q24).
        base['message'] = (('' if any(answered) else 'Энэ талаар мэдээлэл олдсонгүй. ') + referral.get('text', '')).strip()
    else:
        base.pop('referral', None)
        base['message'] = ''
    base.pop('teacher_cards', None)
    return base
