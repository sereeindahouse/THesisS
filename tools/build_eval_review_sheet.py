"""Write a plain Mongolian review sheet for a draft evaluation question set.

The person reviewing reads each question and its expected answer, writes OK or a correction,
and only then is the set locked. The sheet shows no system output, so the review stays
independent of the system's answers.

    python tools/build_eval_review_sheet.py data/eval/system-questions-draft-20261117.json \
        CORE/eval-review/Шалгах_асуулт_хянах_20261117.mn.md
"""
import json
from pathlib import Path
import sys

KIND_MN = {'answerable': 'Хариутай', 'reception': 'Ресепшний хүснэгт', 'compound': 'Хоёр асуулттай',
           'unanswerable': 'Хариугүй (мэдэхгүй гэж хэлж, хаана хандахыг заах ёстой)'}
ORIGIN_MN = {'facebook_test_20261116': 'Facebook чатын 11/16-ны туршилтын асуулт',
             'classes_table': 'сургуулийн анги бүлгийн хүснэгт', 'rooms_table': 'сургуулийн өрөөний хүснэгт',
             'staff_table': 'сургуулийн ажилтны хүснэгт', 'department_page': 'тэнхимийн хуудас (сайт)',
             'department_page_v2': 'тэнхимийн хуудасны дэлгэцэнд харагддаггүй өгөгдөл (сайт)', 'site': 'сургуулийн сайт',
             'agent': 'агентын бичсэн хариугүй асуулт'}


def main(source, target):
    data = json.loads(Path(source).read_text(encoding='utf-8'))
    lines = ['# Шалгах асуултын багц — хянах хуудас (ноорог)', '',
             'Систем зөв хариулж байгаа эсэхийг шалгах асуултууд. Зөв хариултыг агент сайт, сургуулийн хүснэгтээс '
             'бичсэн; системийн хариултыг харж бичээгүй. **Та мөр бүрийг уншаад «Таны тэмдэглэл»-д OK эсвэл засварыг '
             'бичнэ.** Бүгдийг хянасны дараа багцыг түгжинэ; түгжсэний дараа асуулт, хариултыг өөрчлөхгүй.', '',
             '«tune» — системийг сайжруулахад харж болох хэсэг; «test» — зөвхөн эцсийн дүнд. '
             'Ресепшний 30 асуулт (11/09-нд таны түгжсэн) тусдаа, энд давтагдаагүй.', '']
    for kind, label in KIND_MN.items():
        rows = [q for q in data['questions'] if q['kind'] == kind]
        if not rows:
            continue
        lines += [f'## {label} ({len(rows)})', '', '| № | Асуулт | Зөв хариултад байх ёстой | Хаанаас | Хэсэг | Таны тэмдэглэл |',
                  '|---|---|---|---|---|---|']
        for q in rows:
            if q.get('expect') == 'abstain':
                expected = 'хариулахгүй; ресепшн/утас заана'
            else:
                expected = ', '.join(q.get('required_values') or []) or ('нэг нь: ' + ', '.join(q.get('any_of') or []))
            origin = ORIGIN_MN.get(q.get('origin'), q.get('origin', ''))
            note = (' — ' + q['note']) if q.get('note') else ''
            lines.append(f"| {q['id']} | {q['query']} | {expected}{note} | {origin} | {q['split']} |  |")
        lines.append('')
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main(*sys.argv[1:3])
