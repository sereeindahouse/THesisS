"""Offline, escaped viewer for a private synthetic voice-loop run."""
from html import escape
import json
from pathlib import Path
import re


def render(report):
    if report.get('synthetic_voice') is not True:raise ValueError('Synthetic report provenance required.')
    score=report.get('synthetic_text_score') or {}
    rows=report.get('cases',[])
    body=[]
    date=escape(report.get('created_utc','')[:10])
    questions=len({r['query'] for r in rows})
    for query in dict.fromkeys(r['query'] for r in rows):
        cards=[]
        for row in (r for r in rows if r['query']==query):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',row['id']):raise ValueError('Unsafe report case ID.')
            name='bataa' if 'Bataa' in row['voice'] else 'yesui'
            voice='Батаа' if name=='bataa' else 'Есүй'
            stem=row['id']+'-'+name
            response=row.get('raw_response',{})
            route=response.get('route','—')
            answer=response.get('answer') or response.get('message','')
            smoke=row.get('raw_smoke',{})
            label=('Алдаа бүртгэгдсэн' if row.get('error') else 'Тодруулах асуулт' if route=='D'
                   else 'Эхэд мэдээлэл дутуу' if route=='E' else 'Эхтэй нягтлах хариулт')
            cards.append(f'''<article class="voice"><div class="voice-head"><strong>{voice}</strong><span>{escape(label)} · {escape(route)}</span></div>
            <p class="caption">Асуултыг машинаар уншуулсан дуу</p><audio controls preload="metadata" src="{stem}-question.mp3"></audio>
            <p class="caption">STT-ийн өөрчлөлтгүй текст</p><p class="transcript">{escape(row.get('raw_stt','Текст гараагүй'))}</p>
            <p class="caption">Системийн хариултын дуу</p><audio controls preload="metadata" src="{stem}-answer.mp3"></audio>
            <details><summary>Хариулт ба шалгалтын тайлбар</summary><pre>{escape(answer)}</pre>
            <p>Замын шалгуур: {'таарсан' if smoke.get('route_matches') else 'нягтлах'} · Гол үг/тоо: {'байгаа' if smoke.get('field_patterns_present') else 'нягтлах'}.</p>
            <p class="caption">Эдгээр нь автомат smoke шалгалт. Утгын зөв байдлын баталгаа биш.</p>
            {('<p class="error">'+escape(row['error'])+'</p>') if row.get('error') else ''}</details></article>''')
        body.append('<section class="question"><h2>'+escape(query)+'</h2><div class="pair">'+''.join(cards)+'</div></section>')
    wer=f"{score['corpus_wer']:.1%}" if 'corpus_wer' in score else '—'
    cer=f"{score['corpus_cer']:.1%}" if 'corpus_cer' in score else '—'
    return f'''<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Дууны автомат туршилт · THesisS</title>
    <style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f6f0;color:#18382d;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:32px 20px}}.eyebrow,.caption{{color:#64756a;font-size:13px}}h1{{font-size:clamp(28px,5vw,46px);line-height:1.15;margin:12px 0}}h2{{font-size:20px;line-height:1.4;margin:0 0 18px}}.note{{max-width:800px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}}.metric{{background:#e4eadc;border-radius:16px;padding:16px}}.metric strong{{display:block;font-size:29px}}.metric small{{display:block}}.question{{background:white;padding:24px;border:1px solid #dce4d6;border-radius:22px;margin:22px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.voice{{min-width:0;padding:20px;background:#f9faf6;border-radius:16px}}.voice-head{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px}}.voice-head span{{font-size:12px;border-radius:12px;padding:4px 9px;background:#e7ecdf}}audio{{width:100%;height:42px}}.transcript{{background:white;border-left:3px solid #779668;padding:12px;min-height:75px}}details{{margin-top:16px}}summary{{cursor:pointer;color:#4c6c43}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}.error{{color:#9c3b2c}}footer{{font-size:13px;color:#64756a}}@media(max-width:650px){{.pair{{grid-template-columns:1fr}}.metrics{{grid-template-columns:1fr 1fr}}.question{{padding:16px}}main{{padding:20px 12px}}}}</style>
    <main><div class="eyebrow">THesisS · {date} · ХУВИЙН ТУРШИЛТЫН ХАРАГДАЦ</div><h1>Дуунаас хариулт хүртэл.</h1>
    <p class="note">{questions} асуултыг Батаа, Есүй хоолойгоор уншуулж, локал STT → RAG → хариултын TTS урсгалыг ажиллуулсан. Доор оролт, таньсан текст, хариултыг сонсож нягтална.</p>
    <div class="metrics"><div class="metric"><strong>{report.get('completed_clips',0)} / {len(rows)}</strong><small>Хариултын аудио тайлагдсан</small></div><div class="metric"><strong>{wer}</strong><small>Синтетик текстийн WER</small></div><div class="metric"><strong>{cer}</strong><small>Синтетик текстийн CER</small></div><div class="metric"><strong>2</strong><small>TTS хоолой · {questions} асуулт</small></div></div>
    <p class="note">Энэ дууг машинаар үүсгэсэн. Хүний бодит яриа, дуудлагын сонсголын чанар, чатны нийт зөв хариултын хувийг хэмжээгүй. WER/CER нь TTS-д өгсөн текст ба raw STT-ийн ялгаа; модель дахин сургаагүй.</p>
    {''.join(body)}<footer>Туршилтын бүтэн лог: results.json. Аудио/текст локал runtime хавтсанд хадгалагдана. Хүний үнэлгээ бөглөөгүй.</footer></main></html>'''


def write_report(path,replace=False):
    report=json.loads(path.read_text(encoding='utf-8'))
    target=path.parent/'index.html'
    with target.open('w' if replace else 'x',encoding='utf-8',newline='\n') as handle:handle.write(render(report))
    return target
