"""Cut the saved school pages into sections (page title -> heading -> text) for website_sections.py.

The saved HTML of a page marks its headings (h2–h4); the page's saved text is cut at those lines, so a section is
a heading with the text under it, in the page's own words. A page whose saved HTML marks fewer than two headings
in its text (the department pages) is cut at short capitalised lines that are followed by a paragraph. A news or
event page is one section under its title. Left out: listing pages (tiles, pagination), the contact form, the
registration page (stored answers cover it), contact blocks, footers, navigation rows, and every line that holds
a staff mobile number. Nothing is rewritten, and no network or model is used.

    .venv/Scripts/python.exe tools/build_website_sections.py            # -> runtime/website-sections.json
    .venv/Scripts/python.exe tools/build_website_sections.py --list     # print the sections, write nothing

The file names the corpus it was cut from and is ignored for any other corpus: run this again whenever a new
website release is published (tools/build_chat_clone.py runs it before it copies the file).
"""
import argparse
from datetime import datetime, timezone
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from privacy_filter import MOBILE  # noqa: E402
from website_sections import SECTIONS_PATH  # noqa: E402

MIN_TEXT = 60
# Pages that only list other pages (tiles, pagination), a form, or the registration page (stored answers cover it).
INDEX_PAGE = re.compile(r'https://nmct\.edu\.mn/(?:news(?:\?page=\d+)?|events|departments|programs|career|contact|elselt)?/?$')
ARTICLE = re.compile(r'https://nmct\.edu\.mn/(?:news|events)/[^/?#]+$')
NOISE = re.compile(r'^(?:[\d\s.,+%/₮:\-–]+|[぀-ヿ㐀-鿿\s·]+|[^\w\s]+|NEW)$')
NUMBER = re.compile(r'^\d[\d\s.,]*[+%]?$')
VIEWS = re.compile(r'^(\d{4} оны \S+ сарын \d{1,2})\s+\d+\s+үзсэн$')      # a news item's date and its view counter
# Navigation rows, buttons and calls to action printed on every page.
CHROME = re.compile(r'^(?:Нүүр\s+\S.*|Манайд элсэх үү\?|Онлайн элсэлтэд бүртгүүлж.*|Элсэлт|Тэнхимүүд|Бүртгүүлэх(?:\s+Холбоо барих)?|'
                    r'Буцах(?:\s+.*)?|Холбогдох|Нэвтрэх|Дэлгэрэнгүй(?:\s+үзэх)?|Бүгдийг үзэх|Татах|Хөтөлбөр, төлөвлөгөө\s+Холбоо барих|'
                    r'Тэнхимийн тухай\s+.*Амжилт|Дарааллаар нь онцлох үйл явдлуудыг үзээрэй\.|Нэгж дээр дарахад.*|'
                    r'Ирээдүйн мэргэжлээ өнөөдөр сонгож.*)$')
# A section under one of these headings is a footer, a contact block (staff phones are printed there) or a quote.
SKIP_HEADINGS = frozenset({'холбоо барих', 'холбоосууд', 'хөтөлбөрүүд', 'манайд элсэх үү?', 'мэдэгдэл илгээх',
                           'та бидэнтэй нэгдэхэд бэлэн үү?', 'оюутан төгсөгчдийн сэтгэгдэл', 'таны карьер эндээс эхэлнэ',
                           'файлын мэдээлэл'})
HEADING_END = re.compile(r'[.!?…;,:]$')
COMPANY_END = re.compile(r'(?:Ltd|Inc|Co|ХХК|ХК)\.?$')


def flat(text):
    return ' '.join(str(text or '').split())


def key(text):
    return flat(text).casefold()


def clean_lines(text, headings=()):
    """The page's lines without navigation, decoration and staff mobiles. A figure printed on a line of its own
    stays with the caption under it («3270+» / «ном, сурах бичиг» -> «3270+ ном, сурах бичиг»); a card's ordinal
    («01») and a caption left without its figure go. ``headings`` are the page's own heading lines, never joined."""
    keep = {key(heading) for heading in headings}
    raw = [flat(line) for line in (text or '').split('\n')]
    raw = [line for line in raw if line]
    lines, index, ordinal = [], 0, None
    while index < len(raw):
        line = raw[index]
        # Cards are numbered 01, 02 … 09, 10: the «10» after «09» is a card's number too, not a figure.
        if re.fullmatch(r'0\d', line) or (ordinal is not None and ordinal >= 9 and line.isdigit()
                                          and int(line) == ordinal + 1):
            ordinal = int(line)
            index += 1
            continue
        following = raw[index + 1] if index + 1 < len(raw) else ''
        caption = (bool(following) and len(following) <= 40 and key(following) not in keep
                   and not HEADING_END.search(following) and not NUMBER.match(following))
        if key(line) == 'бүх мэдээ':                 # a news page's back link, then its category
            index += 2 if len(following) <= 60 and not VIEWS.match(following) else 1
            continue
        viewed = VIEWS.match(line)
        if MOBILE.search(line):
            pass
        elif viewed:
            lines.append(viewed.group(1))
        elif NUMBER.match(line) and caption:
            lines.append(line + ' ' + following)
            index += 1
        elif line == 'NEW' and caption:
            index += 1
        elif not NOISE.match(line) and not CHROME.match(line):
            lines.append(line)
        index += 1
    return lines


def html_headings(html):
    """[(level, text)] of the h1–h4 headings outside the page's navigation, header and footer."""
    for tag in ('script', 'style', 'nav', 'footer', 'header'):
        html = re.sub(r'<' + tag + r'\b.*?</' + tag + r'\s*>', ' ', html, flags=re.S | re.I)
    found = []
    for match in re.finditer(r'<h([1-4])\b[^>]*>(.*?)</h\1\s*>', html, flags=re.S | re.I):
        text = flat(re.sub(r'<[^>]+>', ' ', match.group(2)).replace('&amp;', '&').replace('&nbsp;', ' ')
                    .replace('&quot;', '"').replace('&#39;', "'"))
        if text:
            found.append((int(match.group(1)), text))
    return found


def says_something(line):
    return len(line) >= 60 or (len(re.findall(r'[^\W\d_]{2,}', line)) >= 4 and re.search(r'[.!?…]$', line) is not None)


def is_label(line, before=None, level=3):
    """The small label printed above a heading: a short line in capitals («ЯПОНД АЖИЛД ОРОХ ЗАМ»), or a short
    capitalised one above a page's main (h2) heading («Дэд бүтэц», «Захирлын мэндчилгээ») or after a paragraph.
    A quotation (the school's motto), a figure with its caption («12 Салбар нэгж») and a card's chip («Эргономик
    тавилга», which follows other chips above a lower heading) are not labels."""
    if line[:1] in ('"', '“', '«', "'") or line[:1].isdigit():
        return False
    letters = [char for char in line if char.isalpha()]
    if 4 <= len(letters) <= 60 and len(line) <= 70 and all(char.isupper() for char in letters):
        return True
    return ((level == 2 or (before is not None and says_something(before))) and len(line) <= 40 and line[:1].isupper()
            and len(re.findall(r'[^\W\d_]{2,}', line)) <= 4 and not HEADING_END.search(line))


def cut_by_headings(title, lines, headings):
    """Sections at the lines that are the page's own HTML headings; None when fewer than two of them are found.
    The text under a contact or footer heading belongs to no section."""
    nodes, pointer = [], 0
    for level, text in headings:
        if level == 1:
            continue
        index = next((i for i in range(pointer, len(lines)) if key(lines[i]) == key(text)), None)
        if index is not None:
            nodes.append((index, level, lines[index], key(text) in SKIP_HEADINGS))
            pointer = index + 1
    if sum(not skipped for _, _, _, skipped in nodes) < 2:
        return None
    starts = {index for index, _, _, _ in nodes}
    labels = {index - 1 for index, level, _, skipped in nodes if not skipped and index > 0 and index - 1 not in starts
              and is_label(lines[index - 1], lines[index - 2] if index > 1 else None, level)}
    sections = []
    intro = [line for i, line in enumerate(lines[:nodes[0][0]]) if i not in labels and key(line) != key(title)]
    if len('\n'.join(intro)) >= MIN_TEXT:
        sections.append(dict(heading=title, label='', parent='', text='\n'.join(intro)))
    for position, (index, level, heading, skipped) in enumerate(nodes):
        if skipped:
            continue
        following = nodes[position + 1] if position + 1 < len(nodes) else None
        has_children = following is not None and following[1] > level and not following[3]
        # A heading with sub-headings keeps their text too (each as a block of its own); one without them ends
        # at the next heading. Either ends at a contact or footer heading.
        end = next((nodes[k][0] for k in range(position + 1, len(nodes)) if nodes[k][1] <= level or nodes[k][3]),
                   len(lines)) if has_children else (following[0] if following else len(lines))
        body = []
        for i in range(index + 1, end):
            if i in labels:
                continue
            if i in starts and body:
                body.append('')
            body.append(lines[i])
        text = '\n'.join(body).strip()
        parent = next((nodes[k][2] for k in range(position - 1, -1, -1) if nodes[k][1] < level and not nodes[k][3]), '')
        if len(text) >= MIN_TEXT:
            sections.append(dict(heading=heading, label=lines[index - 1] if index - 1 in labels else '', parent=parent,
                                 text=text))
    return sections


def heading_like(line):
    words = re.findall(r'[^\W\d_]{2,}', line)
    return (2 <= len(line) <= 70 and 1 <= len(words) <= 9 and line[:1].isupper()
            and (not HEADING_END.search(line) or COMPANY_END.search(line) is not None))


def cut_by_shape(title, lines):
    """Sections at short capitalised lines followed by a paragraph (a second such line right after is a subtitle).
    A contact or footer heading ends the page: what follows it (names, e-mails, phones, calls to action) belongs
    to no section."""
    sections, heading, body = [], title, []

    def close():
        text = '\n'.join(line for line in body if key(line) != key(heading)).strip()
        if len(text) >= MIN_TEXT:
            sections.append(dict(heading=heading, label='', parent='', text=text))
    for index, line in enumerate(lines):
        if key(line) in SKIP_HEADINGS:
            break
        after = lines[index + 1] if index + 1 < len(lines) else None
        second = lines[index + 2] if index + 2 < len(lines) else None
        starts = heading_like(line) and after is not None and (
            says_something(after) or after.startswith('•')
            or (heading_like(after) and second is not None and says_something(second)))
        if starts:
            # A short heading-like line right above a heading is that heading's own over-title, not the end of
            # the text before it («Зорилго, зорилт» above «Үндсэн зорилго»).
            while body and len(body[-1]) <= 40 and heading_like(body[-1]) and not says_something(body[-1]):
                body.pop()
            close()
            heading, body = line, []
        else:
            body.append(line)
    close()
    merged = {}
    for item in sections:        # a heading printed twice on a page is one section
        merged.setdefault(item['heading'], []).append(item['text'])
    return [dict(heading=name, label='', parent='', text='\n'.join(dict.fromkeys(parts))) for name, parts in merged.items()]


def html_file(recorded, release_data):
    """The saved HTML of a capture: the recorded path, or the same file name under this release's snapshots."""
    path = Path(recorded)
    if path.is_file():
        return path
    return next(iter(sorted(release_data.rglob(path.name))), None) if path.name else None


def build(website_database):
    """([section dict], [(url, how it was cut, sections)]) for the latest version of every saved page."""
    website_database = Path(website_database)
    release_data = next((parent for parent in website_database.parents if parent.name == 'data'), website_database.parent)
    sections, report = [], []
    with sqlite3.connect(f'file:{website_database.as_posix()}?mode=ro', uri=True) as connection:
        pages = connection.execute(
            'select p.url, p.version, p.title, p.text, p.retrieved_at from pages p '
            'join (select url, max(version) as version from pages group by url) latest '
            'on latest.url = p.url and latest.version = p.version order by p.url').fetchall()
        for url, version, title, text, retrieved_at in pages:
            title = flat(title)
            if INDEX_PAGE.match(url) or not title or not text:
                continue
            if ARTICLE.match(url):
                body = '\n'.join(line for line in clean_lines(text) if key(line) != key(title))
                parts, how = ([dict(heading=title, label='', parent='', text=body)] if len(body) >= MIN_TEXT else []), 'article'
            else:
                headings = []
                for (recorded,) in connection.execute('select html_path from captures where url=? and version=?', (url, version)):
                    path = html_file(recorded, release_data)
                    if path is not None:
                        headings = html_headings(path.read_text(encoding='utf-8', errors='replace'))
                        break
                lines = clean_lines(text, [heading for _, heading in headings])
                parts = cut_by_headings(title, lines, headings)
                how = 'html headings' if parts is not None else 'line shape'
                if parts is None:
                    parts = cut_by_shape(title, lines)
                # A long section whose own text has headed parts (companies under «Хамтын ажиллагаа») gets them too.
                for part in list(parts):
                    if len(part['text']) > 1200:
                        inner = [item for item in cut_by_shape(part['heading'], part['text'].splitlines())
                                 if key(item['heading']) != key(part['heading'])]
                        known = {key(item['heading']) for item in parts}
                        parts += [dict(item, parent=part['heading']) for item in inner if key(item['heading']) not in known]
            report.append((url, how, len(parts)))
            for part in parts:
                sections.append(dict(url=url, version=version, title=title, retrieved_at=retrieved_at or '', **part))
    return sections, report


def write(root=ROOT):
    """Cut the corpus the chat serves and store the sections; returns (path, sections, report, corpus ID)."""
    from chat_server import content_databases
    from website_retrieval import WebsiteRetriever
    root = Path(root)
    _, website_database, _ = content_databases(root)
    corpus_id = WebsiteRetriever(root=root, database=website_database, use_dense=False).status().get('corpus_id')
    sections, report = build(website_database)
    target = root / SECTIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(schema_version=1, corpus_id=corpus_id,
                                      built_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                      sections=sections), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return target, sections, report, corpus_id


def refresh(root=ROOT):
    """Cut the sections again when the stored ones were cut from another corpus than the one served now;
    returns whether they were cut. Called before the main server starts (open_demo.py)."""
    from chat_server import content_databases
    from website_retrieval import WebsiteRetriever
    root = Path(root)
    _, website_database, _ = content_databases(root)
    corpus_id = WebsiteRetriever(root=root, database=website_database, use_dense=False).status().get('corpus_id')
    try:
        stored = json.loads((root / SECTIONS_PATH).read_text(encoding='utf-8')).get('corpus_id')
    except (OSError, ValueError, AttributeError):
        stored = None
    if corpus_id and stored == corpus_id:
        return False
    write(root)
    return True


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--list', action='store_true', help='print the sections and write nothing')
    parser.add_argument('--url', default='', help='with --list: only pages whose address holds this text')
    args = parser.parse_args()
    if args.list:
        from chat_server import content_databases
        _, website_database, _ = content_databases(ROOT)
        sections, report = build(website_database)
        corpus_id = None
        for item in sections:
            if args.url in item['url']:
                print(f"{len(item['text']):5d} | {item['url'].replace('https://nmct.edu.mn', '')[:40]:40s} | "
                      f"{(item['label'] + ' / ' if item['label'] else '') + item['heading']}"[:150]
                      + (f"   (under: {item['parent']})" if item['parent'] else ''))
    else:
        target, sections, report, corpus_id = write(ROOT)
        print('wrote', target)
    how = {}
    for _, kind, count in report:
        how.setdefault(kind, [0, 0])
        how[kind][0] += 1
        how[kind][1] += count
    print(len(sections), 'sections from', len(report), 'pages;',
          {kind: f'{pages} pages, {count} sections' for kind, (pages, count) in how.items()},
          '| corpus', str(corpus_id)[:12])


if __name__ == '__main__':
    main()
