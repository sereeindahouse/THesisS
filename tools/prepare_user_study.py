"""Prepare private, empty human-study materials; never collect or invent results.

Example (choose pseudonyms and recruitment size yourself):
  python tools/prepare_user_study.py --cases <private-frozen-cases.json>
    --passages <frozen-passages.json> --participants P001 P002 P003 --seed 71
    --output-dir runtime/user-study-prepared-01

No HTTP/model/audio calls. Use full source-quote references, not a collector output.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_answer_cases import validate

CONDITIONS = ('typed', 'raw', 'explicit-edited')
DIMENSIONS = ('correctness', 'citation_support', 'answer_relevance', 'completeness',
              'abstention', 'clarification', 'response_appropriateness')
OBSERVATION_KEYS = {'response', 'responses', 'results', 'assistant_review', 'stt_text',
                    'raw_stt', 'hypothesis', 'generated_reference', 'stt_generated_reference',
                    'model_output', 'transcript', 'participant_result'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _no_observations(value):
    """A preparation input is not an output log or an auto-transcribed gold file."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in OBSERVATION_KEYS or key == 'human_review' and child is not None:
                raise ValueError('Preparation requires unfilled references, not results/transcript-derived gold.')
            _no_observations(child)
    elif isinstance(value, list):
        for child in value:
            _no_observations(child)


def _norm(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


PROTOCOL = '''# Хүний туршилтын бэлтгэсэн протокол — үр дүн цуглараагүй

Энэ нь хязгаартай pilot-ийн материал; багш баталсан дизайн, хүний gold эсвэл
оролцогчийн тоо/power-ийн тооцоо биш. Оператор recruitment, бодит оролцогчийн тоо,
зогсоох нөхцөл, боломжит хугацааг урьдчилан шийдэж тэмдэглэнэ. P001 зэрэг ID нь
нэр биш. Зөвшөөрөл авсан эсэхийг загвар автоматаар бөглөхгүй. Оролцогч дуугаа
хадгалуулахгүйгээр татгалзах, завсарлах, дуусгах эрхтэй. Хувийн холбоо барих
мэдээлэл, зөвшөөрлийн эхийг энэ сангаас тусад нь хариуцан хадгална.

Оролцогчид өгөгдлийн урсгалыг урьдчилан тайлбарлана: STT-д ашиглах микрофоны эсвэл
оруулсан аудиог төслийн локал серверт Whisper боловсруулна; гадаад STT үйлчилгээ
рүү илгээхгүй. Харин «Сонсох» үйлдэл ашиглах үед тухайн хариултаас сонгосон
синтезийн текст, сонгосон voice/хэлний тохиргоо онлайн Edge/Microsoft TTS үйлчилгээ
рүү очно. Үүнийг бичлэгээ тэр үйлчилгээ рүү илгээсэн гэж ойлгуулахгүй; бүх урсгалыг
бүрэн офлайн гэж танилцуулахгүй. Сонсголын туршилт эхлэхээс өмнө энэ ялгааг ойлгосон
эсэх, аудио хадгалуулах сонголтыг бодит зөвшөөрлийн бүртгэлд тусад нь тэмдэглэнэ.

## Бэлтгэл ба нөхцөл оноолт

Эхийн snapshot, асуулт, required facts, rubric болон tool-ийн SHA256 manifest-д
байна. Assistant-authored reference нь хүний баталсан зөв хариу биш. Домэйныг
мэдэх хүн эх/required facts-ийг гаралттай харьцуулахаас өмнө шалгаж болно; хуучин
freeze-ийг өөрчилж болохгүй, өөр хувилбар/шалтгаан/цагийг тусад нь хадгална.
Туршилтын өмнө browser/device, HTTPS эсвэл loopback secure context, mic permission,
сүлжээ, model/loaded artifact hashes, decoder, voice, cold/warm төлөвийг тэмдэглэ.
Нэг ижил хувилбар хэрэглэ; тасалдал болон retry-г устгахгүй.

Тухайн оролцогч нэг кейсийг нэг удаа гүйцэтгэнэ. Гурван нөхцөлийн оноолт кейс бүрт
оролцогчийн 0/1/2 бүлгээр ээлжилнэ; гурван оролцогч бүрд case-condition тэнцэнэ.
Тоо 3-т хуваагдахгүй үед үлдэгдэл тэнцвэргүйг нуудаггүй. Task order seed-тэй,
оролцогч бүрт rotate/reverse хийсэн; энэ нь бүрэн randomized controlled trial биш.
Нэг session-д default 6 task нь амралттай жижиг pilot-ийн зохион байгуулалтын
санал; шаардлагатай N, power, validated fatigue threshold биш. Operator өөрчилж
болно. Practice task-ийг scored task-аас тусдаа, давхардаагүйгээр бэлтгэ.

typed: оролцогч өөрийн хүсэлтийг бичнэ. Үнэхээр илгээсэн text-ийг хадгална.
raw: оролцогч ярьж, STT-ийн анхны гаралтыг ямар ч засваргүй яг илгээнэ.
explicit-edited: анхны audio/raw STT-г хадгалж, оролцогч өөрөө transcript-ийг
засах эсвэл хэвээр нь зөвшөөрч ил тод Apply/confirm хийнэ. Илгээсэн text, edit,
баталгаажуулсан үйлдэл/цагийг тусад нь бичнэ. Автомат засвар эсвэл reference-ээр
солихыг хүний edit гэж нэрлэхгүй. Raw ба edited task-ууд ижил audio биш; энэ
дизайн decoder-ийн paired WER improvement-ийг дангаар тусгаарлаж тогтоохгүй.

## Бодит бүртгэл

facilitator.forms.json-ийн null талбаруудыг зөвхөн бодит үйл явдлаар бөглөнө.
timing_events_ms нь нэг trial-ийн ижил monotonic clock; UTC-г тусдаа хадгална.
task_presented→task_completed: task time; recording_stopped→stt_completed: STT wait;
request_sent→answer_received: RAG wall time; tts_request_sent→tts_ready: synthesis
wait; playback_started→playback_completed: тоглуулах хугацаа. Editing time-ийг
edit_started→edit_confirmed-аар тусад нь хэмж. Байхгүй event-ээс хугацаа зохиохгүй.
HTTP/status/error, retry, clarification turn, actual sent text, immutable audio SHA,
raw STT, explicit edit, answer/spoken text/citations, response/audio binding ID-г
хадгал. Инженерийн timing ба хүний хүлээн зөвшөөрсөн latency-г хольж болохгүй.

TTS: файл decode/load/play болсон эсэх нь хүний сонссон, ойлгосон нотолгоо биш.
Бодит хүн сонссон эсэх, дуустал сонссон эсэх, алдаатай сонссон үг, intelligibility
1=ойлгох боломжгүй … 5=бүх үг ойлгомжтой, naturalness 1=маш хиймэл … 5=маш
жам ёсны гэсэн хоёр тусдаа үнэлгээ ав. Сонсоогүй бол rating=null хэвээр.
task_success: оролцогчийн өөрийн дүгнэлт болон facilitator-ийн эх/required facts-д
тулгасан дүгнэлтийг тусад нь хадгал. Асуулт тодруулсан, зөв татгалзсан task нь
хэрэгцээг зөв шийдсэн байж болно. Route, quote membership-ээр success бөглөхгүй.
Эхний task-аас дараагийн task-д хариу зааж өгөхгүй; тусламж өгсөн бол тэмдэглэ.

ASR WER/CER-ийг зөвхөн тухайн аудиог хүн сонсож тусад нь баталсан actual utterance
reference-тэй бодож болно. Task question, model hypothesis, edited intent-ийг ASR
gold болгож автоматаар хуулж болохгүй. 13 өмнөх confirmed reference ба pending
recording-уудыг энэ study-ийн шинэ яриатай нийлүүлэхгүй. Байгалийн яриа, synthetic
audio, silence/noise controls-ийн denominator-уудыг тусдаа тайлагна.

## Condition-ийг нуусан хариултын үнэлгээ

blind-review.forms.json-ийг reviewer-д өг; linkage.private.json болон facilitator
forms-ийг бүү өг. Blind form-д condition/route/model/participant ID байхгүй.
Оператор зөвхөн бодитоор гарсан answer/spoken text/citations болон хүн баталсан
intended request-ийг review_id-аар хуулна; анхны raw log-ийг өөрчлөхгүй. Хэрэв
оролцогч task-аас өөр зүйл асуусан бол үүнийг тэмдэглэж, зориулсан field-ийн
хариуг хүчээр оноохгүй. Text-ээс нөхцөл таамаглагдаж болох тул бүрэн blindness
батлахгүй. Үнэлэгч implementation-д оролцсон эсэхээ заавал мэдүүлнэ; оролцоогүй
хүнийг боломжтой бол сонго. AI review-г human_review-д бичихгүй.

Case rubric-ийн pass/partial/fail/not_applicable-ийг dimension болон required fact
тус бүрт шалтгаантай бөглөнө. Correctness, citation support, relevance, completeness,
abstention, clarification, appropriateness тусдаа. Citation-д байгаа боловч answer/
spoken text-д дутсан гол fact-ийг автоматаар нөхсөн гэж үзэхгүй. Давхар reviewer
байвал эхний үнэлгээг дарж засахгүй, санал зөрөлдөөний adjudication-ийг тусад нь
хадгал; бодит reviewer хүрэлцэхгүй бол independent consensus гэж нэрлэхгүй.

## Тайлагнах хүрээ

Хэдэн хүн эхэлсэн/дууссан, хэдэн trial/condition, incomplete/error/withdrawn,
task difficulty/order/device/cold-warm бүлгийг denominator-тай тайлагна. Жижиг
convenience pilot-ийг бүх хэрэглэгчид generalize хийхгүй, causal significance эсвэл
sample-size sufficiency батлахгүй. Median/IQR latency, task success, listening
rating, edits/clarification, blind fact judgments-ийг тусад нь үзүүлж raw logs-ийг
хувийн хэвээр хадгал. Шинэ кейсээр production зассан бол цааш development.
Энэ tool зөвхөн хоосон загвар бэлтгэнэ; actual participation/results=0 хэвээр.
'''


def prepare(cases_path, passages_path, output_dir, participants, seed, tasks_per_session=6):
    cases_path, passages_path, output_dir = map(Path, (cases_path, passages_path, output_dir))
    if (not participants or len(participants) > 300 or len(set(participants)) != len(participants)
            or any(not re.fullmatch(r'P[0-9]{3,6}', p) for p in participants)):
        raise ValueError('Supply distinct pseudonyms P001 etc.; no participant count is inferred.')
    if type(seed) is not int or type(tasks_per_session) is not int or not 1 <= tasks_per_session <= 12:
        raise ValueError('Use an integer seed and 1–12 tasks per session.')
    private_root = (ROOT/'runtime').resolve()
    if private_root not in output_dir.resolve().parents:
        raise ValueError('Study materials must stay in a new private runtime subdirectory.')
    if output_dir.exists():
        raise FileExistsError('Keep prior prepared materials/results; choose a new output directory.')
    # Read once: the parsed data and their provenance identify the same exact bytes.
    cases_bytes, source_bytes = cases_path.read_bytes(), passages_path.read_bytes()
    bundle = json.loads(cases_bytes.decode('utf-8-sig'))
    passages = json.loads(source_bytes.decode('utf-8-sig'))
    _no_observations(bundle)
    if (bundle.get('label_author') != 'assistant' or bundle.get('human_reference_review') is not False
            or bundle.get('prepared_before_current_system_outputs') is not True):
        raise ValueError('Require explicitly assistant-authored, unreviewed pre-output reference provenance.')
    public, validation = validate(bundle, passages, sha(source_bytes))
    cases = bundle['cases']
    if len({_norm(c['query']) for c in cases}) != len(cases):
        raise ValueError('Duplicate normalized task query.')
    rubric = bundle.get('protocol', {}).get('review_rubric', {})
    if (not rubric.get('prepared_before_model_outputs') or not isinstance(rubric.get('markdown'), str)
            or rubric.get('sha256') != sha(rubric['markdown'].encode('utf-8'))):
        raise ValueError('Require a frozen pre-output rubric and matching SHA256.')
    order = list(range(len(cases)))
    random.Random(seed).shuffle(order)
    trials, participant_forms, reviews = [], [], []
    events = ('task_presented', 'input_started', 'recording_stopped', 'stt_completed',
              'edit_started', 'edit_confirmed', 'request_sent', 'answer_received',
              'tts_request_sent', 'tts_ready', 'playback_started', 'playback_completed', 'task_completed')
    for p_index, participant in enumerate(participants):
        shift = p_index % len(cases)
        task_order = order[shift:]+order[:shift]
        if p_index % 2:
            task_order.reverse()
        tasks = []
        for position, case_index in enumerate(task_order):
            case = cases[case_index]
            condition = CONDITIONS[(case_index+p_index) % 3]
            trial_id = f'{participant}-T{position+1:03d}'
            review_id = 'R'+sha(f'{seed}:{participant}:{case["id"]}'.encode())[:20]
            task = dict(trial_id=trial_id, session=position//tasks_per_session+1,
                        position=position+1, condition=condition, task=case['query'])
            tasks.append(task)
            trials.append(dict(**task, participant_id=participant, case_id=case['id'], review_id=review_id,
                status='not_started', actual_started_utc=None, actual_finished_utc=None,
                timing_events_ms={name: None for name in events}, environment=None,
                actual_input=dict(typed_text=None, audio_path=None, audio_sha256=None,
                    raw_stt=None, edited_text=None, explicit_edit_confirmed=None, sent_text=None,
                    human_listened_utterance_reference=None, human_reference_confirmed=None),
                actual_output=dict(http_status=None, response_id=None, answer=None, spoken_text=None,
                    citations=None, bound_audio_response_id=None, error=None, retries=None,
                    clarification_turns=None, runtime_fingerprint=None),
                tts_listening=dict(audio_loaded=None, playback_observed=None, human_listened=None,
                    listened_to_end=None, intelligibility_1_to_5=None, naturalness_1_to_5=None,
                    misheard_words=None, notes=None),
                task_success=dict(participant_judgment=None, participant_final_answer=None,
                    facilitator_judgment=None, facilitator_id=None, evidence_notes=None),
                protocol_deviations=None))
            reviews.append(dict(review_id=review_id, task=case['query'], intended_request_confirmed_by_human=None,
                reference_answerability=case['reference_answerability'], expected_behavior=case['expected_behavior'],
                required_facts=[dict(fact=fact, judgment=None, evidence_notes=None) for fact in case['required_facts']],
                forbidden_claims=case['forbidden_claims'], frozen_source_refs=case['source_refs'],
                actual_answer=None, actual_spoken_text=None, actual_citations=None,
                human_review=dict(reviewer_id=None, implementation_participation=None,
                    dimensions={name: None for name in DIMENSIONS}, overall=None, notes=None)))
        participant_forms.append(dict(participant_id=participant, consent=None, audio_storage_consent=None,
            started_utc=None, withdrawn=None, sessions_completed=None, tasks=tasks))
    random.Random(seed+1).shuffle(reviews)
    linkage = [dict(review_id=t['review_id'], participant_id=t['participant_id'],
                    trial_id=t['trial_id'], case_id=t['case_id'], condition=t['condition']) for t in trials]
    # Nothing below is an observation. Records remain null until a real human/session.
    metadata = dict(stage='prepared_not_collected', actual_participants=0, completed_trials=0,
                    human_answer_reviews=0, human_listening_ratings=0, results_fabricated=False)
    files = {
        'participant.forms.json': dict(**metadata, participants=participant_forms),
        'facilitator.forms.json': dict(**metadata, event_clock='one monotonic millisecond clock per trial', trials=trials),
        'blind-review.forms.json': dict(**metadata, rubric=rubric, cases=reviews),
        'linkage.private.json': dict(warning='Do not give this linkage or facilitator file to blind reviewers.', rows=linkage),
        'reference-validation.json': validation,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (output_dir/name).open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(content, ensure_ascii=False, indent=2)+'\n')
    (output_dir/'protocol.mn.md').write_text(PROTOCOL, encoding='utf-8', newline='\n')
    manifest = dict(schema_version=1, prepared_utc=datetime.now(timezone.utc).isoformat(), **metadata,
        preparation_only=True, independent_human_evaluation_completed=False, teacher_approved_design=False,
        seed=seed, tasks_per_session=tasks_per_session, planned_participant_pseudonyms=participants,
        planned_trials=len(trials), counterbalance_groups=[dict(participant_id=p, group=i%3) for i,p in enumerate(participants)],
        condition_counts=dict(Counter(t['condition'] for t in trials)),
        preparation_slots_only=True, recruitment_target_n=None,
        sample_size_justification=None, recruitment_plan=None, analysis_plan_human_approved=None,
        source_snapshot_sha256=sha(source_bytes), cases_sha256=sha(cases_bytes),
        case_label_scope=bundle.get('label_scope'), reference_validation=validation,
        tool_sha256=sha(Path(__file__).read_bytes()),
        artifacts={p.name:dict(sha256=sha(p.read_bytes()), bytes=p.stat().st_size) for p in output_dir.iterdir() if p.is_file()},
        limitations=['Counterbalanced pilot materials only; no N/power or teacher approval implied.',
            'Assistant references are not human gold; new actual utterances need separate listening confirmation.',
            'Each task once per participant; raw/edited do not replay the same audio.',
            'No model, HTTP, TTS, microphone, participant or human-review calls made.'])
    with (output_dir/'manifest.json').open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True, help='Private pre-output cases with full exact source quotes.')
    parser.add_argument('--passages', type=Path, required=True, help='Exact frozen source snapshot.')
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory under this project runtime/.')
    parser.add_argument('--participants', nargs='+', required=True, help='Operator-chosen pseudonyms, e.g. P001 P002 P003.')
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--tasks-per-session', type=int, default=6)
    args = parser.parse_args()
    result = prepare(args.cases, args.passages, args.output_dir, args.participants, args.seed, args.tasks_per_session)
    print(json.dumps(dict(output_dir=str(args.output_dir), planned_trials=result['planned_trials'],
                          actual_participants=0, human_answer_reviews=0), ensure_ascii=False))
