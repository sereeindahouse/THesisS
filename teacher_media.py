"""Dated, source-bound teacher portraits; no face recognition or model images.

Only explicitly named teacher objects in a captured official Next Flight record
may supply a profile. Source-labelled sample portraits are excluded independently
of valid text fields. This optional store never edits the RAG content release.
Missing/invalid stores disable the feature, rather than inventing a profile.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import struct
import threading
from datetime import datetime
from urllib.parse import urlsplit

from CORE.client_tab_corpus import flight_records
from CORE.website_corpus import PageParser
from source_fields import staff_query_scope, _scope_words


DEFAULT_MANIFEST = 'runtime/quality-media-20261021/teacher-media/manifest-v2.json'
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
SOURCE_HOST = 'nmct.edu.mn'
ID = re.compile(r'teacher-[a-f0-9]{24}\Z')
HEX = re.compile(r'[a-f0-9]{64}\Z')
PLACEHOLDER = re.compile(r'sample|placeholder|default[-_]?avatar|dummy', re.I)
UNSUPPORTED = re.compile(
    r'утас|дугаар|данс|цалин|гэрийн|гэр бү|төрсөн|нас(?:\W|$)|регист|'
    r'хаяг|имэйл|мэйл|email|salary|account|phone|address|password|age\b|'
    r'өнөөдөр|маргааш|хуваарь|өрөө|хаана|хэзээ|ажиллаж байгаа|одоо ажил', re.I)
PROFILE_INTENT = re.compile(
    r'танилцуул|тухай|хэн\b|зураг|зург(?:ийг|ийн|аа)|хөрөг|ямар багш|ямар ажил|'
    r'мэдээлэл|photo|portrait|profile|who\b|tell me|about', re.I)
OVERVIEW_WORD = re.compile(
    r'багш(?:ийн|ийг|нар(?:ын)?)?|нар(?:ын)?|эрхлэгч(?:ийн)?|тэнхимийн|нь|хэн|бэ|вэ|юм|гэж|'
    r'энэ|тэр|надад|тухай|талаар|танилцуул(?:га|гыг|на|ж|ах|аач|аад)?|'
    r'мэдээлэл|зур(?:аг(?:тай)?|гийг|гаа)|хөрөг|харуул(?:на|ж|ах|аач)?|'
    r'үзүүл(?:нэ|ж|ээч)?|үзье|хэл(?:ж|нэ)?|'
    r'өг(?:нө|өөч|ч)|уу|үү|болох|болон|эсвэл|please|show|me|tell|who|is|'
    r'about|teacher|professor|photo|portrait|profile|picture|a|can|you|of', re.I)


def _generic_staff_overview(query):
    """A closed generic overview request is not automatically a photo request."""
    words = re.findall(r'[^\W_]+', query.casefold())
    allowed = re.compile(r'багш(?:ийн|ийг|нар(?:ын(?:хаа)?)?)?|нар(?:ын(?:хаа)?)?|'
        r'манай|танай|надад|сургууль|сургуулийн|бүх|нь|хэн|хэнтэй|ямар|тухай|талаар|'
        r'мэдээлэл|танилцуул(?:га|гыг|на|ж|ах|аач|аад)?|өг(?:нө|өөч|ч)|'
        r'хэл(?:ж|нэ)?|байдаг|юм|бэ|вэ|уу|үү|please|teacher|teachers|about|tell|me', re.I)
    return bool(words and re.search(r'багш|teacher', query, re.I)
                and all(allowed.fullmatch(word) for word in words))


def _directory_only(query, department):
    """Do not let an unknown person or another requested field disappear."""
    if re.search(r'тоо|хэд|цалин|нас|хичээл|болон|ба\b|эсвэл|харьцуул|зураг|хөрөг', query, re.I):
        return False
    remaining = _scope_words(query) - _scope_words(department)
    return remaining <= set('''багш багшийн багшнар багшнарын нар нарын нэр нэрс нэрсийг нэрийг
        хэн байдаг хэлнэ хэл өгөөч өгч хэлж байна танилцуул танилцуулаач танилцуулга танилцуулгыг жагсаа жагсааж жагсаагаад жагсаалт
        жагсаалтыг үзүүл үзүүлнэ үзүүлээч харуул харуулна харуулаач үү уу вэ бэ юм нартай'''.split())


class TeacherMediaError(ValueError):
    """Stored provenance or asset bytes failed verification."""


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _official_url(value, *, image=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise TeacherMediaError('Invalid official source URL.')
    p = urlsplit(value)
    if (p.scheme != 'https' or p.netloc != SOURCE_HOST or p.query or p.fragment
            or p.username or p.password or '%' in p.path or '..' in p.path.split('/')):
        raise TeacherMediaError('Source URL is outside the fixed official host.')
    if image:
        if not p.path.startswith('/uploads/') or PLACEHOLDER.search(p.path):
            raise TeacherMediaError('Unsupported or placeholder portrait.')
    elif not re.fullmatch(r'/departments/[a-z0-9-]+', p.path):
        raise TeacherMediaError('Unsupported teacher source page.')
    return value


def _safe_file(root, value, limit):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(x in ('', '.', '..') for x in value.split('/'))):
        raise TeacherMediaError('Unsafe media path.')
    try:
        target = (root / value).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise TeacherMediaError('Missing or escaped media path.')
        if target.stat().st_size > limit:
            raise TeacherMediaError('Stored media exceeds size limit.')
        data = target.read_bytes()
        if len(data) > limit:
            raise TeacherMediaError('Stored media exceeds size limit.')
        return data
    except OSError as exc:
        raise TeacherMediaError('Stored teacher media is unreadable.') from exc


def _dimensions(data, mime):
    """Validate allowed raster signatures/dimensions; SVG/HTML are forbidden.

    Collection additionally decodes every downloaded image. Serving compares
    its complete SHA256 with those frozen bytes, so it never fetches a new URL.
    """
    if mime == 'image/png':
        if (len(data) < 45 or not data.startswith(b'\x89PNG\r\n\x1a\n')
                or data[12:16] != b'IHDR' or data[-12:] != b'\0\0\0\0IEND\xaeB`\x82'):
            raise TeacherMediaError('Invalid PNG signature.')
        result = struct.unpack('>II', data[16:24])
    elif mime == 'image/jpeg':
        if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise TeacherMediaError('Invalid JPEG signature.')
        pos, result = 2, None
        while pos + 4 <= len(data):
            if data[pos] != 255:
                raise TeacherMediaError('Invalid JPEG marker.')
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                continue
            size = int.from_bytes(data[pos:pos + 2], 'big')
            if size < 2 or pos + size > len(data):
                raise TeacherMediaError('Invalid JPEG segment.')
            if marker in (0xc0, 0xc1, 0xc2):
                if size < 8:
                    raise TeacherMediaError('Invalid JPEG dimensions.')
                height, width = struct.unpack('>HH', data[pos + 3:pos + 7])
                result = width, height
                break
            pos += size
        if result is None:
            raise TeacherMediaError('JPEG dimensions missing.')
    else:
        raise TeacherMediaError('Unsupported portrait MIME type.')
    if min(result) < 1 or max(result) > 10000 or result[0] * result[1] > 16_000_000:
        raise TeacherMediaError('Unsafe image dimensions.')
    return result


def _at_pointer(value, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise TeacherMediaError('Invalid teacher record pointer.')
    try:
        for part in pointer[1:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise TeacherMediaError('Teacher record pointer does not resolve.') from exc
    return value


def _contains(text, alias):
    # Bounded Mongolian case suffixes, never arbitrary prefix/substring matching.
    return bool(re.search(r'(?<!\w)' + re.escape(alias.casefold()) +
                          r'(?:ын|ийн|ны|ний|ыг|ийг|тай|тэй|аас|ээс|ы|и|д|т)?(?!\w)',
                          text.casefold()))


def _overview_only(query, rows):
    remaining = query.casefold()
    for row in rows:
        for alias in row['aliases']:
            remaining = re.sub(r'(?<!\w)' + re.escape(alias.casefold()) +
                               r'(?:ын|ийн|ны|ний|ыг|ийг|тай|тэй|аас|ээс|ы|и|д|т)?(?!\w)',
                               ' ', remaining)
    # Unknown words (including another unregistered person's name) must not be
    # silently discarded in order to convert a different question into a bio.
    words = re.findall(r'[^\W_]+(?:-[^\W_]+)*', remaining)
    return all(OVERVIEW_WORD.fullmatch(word) for word in words)


class TeacherMedia:
    def __init__(self, root, manifest_path=None):
        self.project_root = Path(root).resolve()
        self.manifest = (Path(manifest_path) if manifest_path else
                         self.project_root / DEFAULT_MANIFEST).resolve()
        if not self.manifest.is_relative_to(self.project_root):
            raise TeacherMediaError('Teacher manifest must be inside project root.')
        self.root = self.manifest.parent
        self._lock = threading.RLock()
        self._cache = None

    def _load(self):
        with self._lock:
            if not self.manifest.is_file():
                raise TeacherMediaError('Teacher media has not been collected.')
            raw = _safe_file(self.root, self.manifest.name, MAX_MANIFEST_BYTES)
            bundle_id = _sha(raw)
            try:
                manifest = (deepcopy(self._cache[1]) if self._cache and self._cache[0] == bundle_id
                            else json.loads(raw))
                profiles = manifest['profiles']
                if (manifest['schema_version'] not in (1, 2) or
                    manifest['method'] != 'explicit_official_next_flight_teacher_record' or
                    not isinstance(profiles, list) or not 1 <= len(profiles) <= 50):
                    raise TeacherMediaError('Unsupported teacher manifest.')
                parsed, seen_ids, seen_people, checked_pages = [], set(), set(), {}
                for item in profiles:
                    if (not isinstance(item, dict) or
                        any(not isinstance(item.get(k), str) or len(item[k]) > 2000
                            for k in ('teacher_id','name','role','bio','department'))):
                        raise TeacherMediaError('Invalid teacher text fields.')
                    source, asset = item['source'], item['image']
                    source_url = _official_url(source['url'])
                    html = _safe_file(self.root, source['html_file'], MAX_HTML_BYTES)
                    if _sha(html) != source['html_sha256']:
                        raise TeacherMediaError('Teacher source capture changed.')
                    page = PageParser(); page.feed(html.decode('utf-8'))
                    department = page.result()['title'].split('|')[0].strip()
                    if source['html_sha256'] not in checked_pages:
                        checked_pages[source['html_sha256']] = flight_records(html.decode('utf-8'))
                    records = checked_pages[source['html_sha256']]
                    teacher = _at_pointer(records[source['record']], source['pointer'])
                    # A name/image object elsewhere in the page is insufficient.
                    if not re.search(r'/teachers/\d+\Z', source['pointer']):
                        raise TeacherMediaError('Source is not an explicit teacher object.')
                    if not isinstance(teacher, dict) or _sha(_canonical(teacher)) != source['teacher_record_sha256']:
                        raise TeacherMediaError('Teacher source object changed.')
                    aliases = [s for s in (teacher['name'], teacher.get('nameEn', '')) if s]
                    if any(not isinstance(alias, str) or len(alias) > 120 for alias in aliases):
                        raise TeacherMediaError('Invalid teacher aliases.')
                    if (item['name'] != teacher['name'] or item['aliases'] != aliases or
                        item['role'] != teacher.get('position', '') or
                        item['bio'] != teacher.get('bio', '') or
                        item['department'] != department or
                        item['teacher_id'] != 'nmct-' + urlsplit(source_url).path.rsplit('/', 1)[1] + '-' + str(teacher['id']) or
                        not item['name'].strip() or not item['role'].strip()):
                        raise TeacherMediaError('Manifest does not match teacher source fields.')
                    if item['teacher_id'] in seen_people:
                        raise TeacherMediaError('Duplicate teacher identity.')
                    seen_people.add(item['teacher_id'])
                    if asset is None:
                        # An explicit source placeholder is a missing portrait,
                        # not a reason to throw away the publisher's named record.
                        # Other absent/malformed images must not silently become
                        # "verified" text-only entries in a damaged v1 bundle.
                        if (manifest['schema_version'] != 2 or
                            item.get('image_omission_reason') != 'source_image_filename_indicates_placeholder' or
                            not isinstance(teacher.get('image'), str) or
                            not teacher['image'].startswith('/uploads/') or
                            not PLACEHOLDER.search(teacher['image']) or
                            '%' in teacher['image'] or '\\' in teacher['image'] or '?' in teacher['image'] or
                            '#' in teacher['image'] or '..' in teacher['image'].split('/')):
                            raise TeacherMediaError('Unverified text-only portrait omission.')
                    else:
                        image_url = _official_url(asset['url'], image=True)
                        if image_url != 'https://' + SOURCE_HOST + teacher['image']:
                            raise TeacherMediaError('Manifest does not match teacher portrait.')
                        mid, sha = asset['media_id'], asset['sha256']
                        if not ID.fullmatch(mid) or not HEX.fullmatch(sha) or mid != 'teacher-' + sha[:24]:
                            raise TeacherMediaError('Invalid media identifier.')
                        if mid in seen_ids:
                            raise TeacherMediaError('Duplicate image identity.')
                        seen_ids.add(mid)
                        image = _safe_file(self.root, asset['file'], MAX_IMAGE_BYTES)
                        if len(image) != asset['bytes'] or _sha(image) != sha:
                            raise TeacherMediaError('Teacher portrait changed.')
                        if _dimensions(image, asset['mime']) != (asset['width'], asset['height']):
                            raise TeacherMediaError('Teacher portrait dimensions differ.')
                    if not isinstance(source['captured_utc'], str) or not source['captured_utc'].endswith(('+00:00', 'Z')):
                        raise TeacherMediaError('Teacher capture must have a UTC timestamp.')
                    datetime.fromisoformat(source['captured_utc'].replace('Z', '+00:00'))
                    item['_bundle_id'] = bundle_id
                    parsed.append(item)
                self._cache = bundle_id, deepcopy(manifest)
                return bundle_id, parsed
            except TeacherMediaError:
                raise
            except (KeyError, TypeError, ValueError, UnicodeError, OSError, OverflowError) as exc:
                raise TeacherMediaError('Invalid teacher media provenance.') from exc

    def status(self):
        try:
            bundle, rows = self._load()
            return dict(available=True, profile_count=len(rows), bundle_id=bundle,
                        portrait_count=sum(item['image'] is not None for item in rows),
                        source_kind='dated_official_teacher_records')
        except (TeacherMediaError, OSError):
            return dict(available=False, profile_count=0, portrait_count=0, bundle_id=None,
                        error='Teacher media is unavailable or failed verification.')

    def catalog(self):
        """Captured profiles only; this is never a complete/current staff list."""
        try:
            _, rows = self._load()
            return [self._card(row) for row in rows]
        except (TeacherMediaError, OSError):
            return []

    @staticmethod
    def _card(item):
        source, asset = item['source'], item['image']
        return dict(teacher_id=item['teacher_id'], name=item['name'], role=item['role'],
                    bio=item['bio'], department=item['department'], media_id=asset['media_id'] if asset else None,
                    image_url='/api/teacher-media/' + asset['media_id'] if asset else None,
                    image_sha256=asset['sha256'] if asset else None,
                    portrait_available=asset is not None,
                    image_status='source_bound_portrait' if asset else 'source_placeholder_excluded',
                    source_url=source['url'],
                    source_fields=dict(name=item['name'], position=item['role'], bio=item['bio']),
                    source_quote='\n'.join(x for x in (item['name'], item['role'], item['bio']) if x),
                    source_quote_kind='structured_teacher_fields',
                    captured_utc=source['captured_utc'], source_html_sha256=source['html_sha256'],
                    source_locator='Flight record ' + source['record'] + ' JSON ' + source['pointer'],
                    bundle_id=item['_bundle_id'])

    def profile(self, query):
        """Only a named-teacher overview/photo request; never answer private fields."""
        if not isinstance(query, str) or not 1 <= len(query) <= 2000 or UNSUPPORTED.search(query):
            return None
        if (not PROFILE_INTENT.search(query) and not _generic_staff_overview(query)
                and not re.search(r'багш\w*(?:\s+нар\w*)?\s+нэр', query, re.I)):
            return None
        try:
            bundle, rows = self._load()
        except (TeacherMediaError, OSError):
            return None
        matches = [row for row in rows if any(_contains(query, alias) for alias in row['aliases'])]
        if not matches:
            # Names are available even when the full staff roster is not. This
            # partial directory uses only already verified portrait records.
            catalog = [dict(title=row['department'],url=row['source']['url'],text='') for row in rows]
            scope = staff_query_scope(query, [], catalog=catalog)
            photo = bool(re.search(r'зураг|зургийг|хөрөг|photo|portrait',query,re.I))
            if scope and (scope['kind']=='names' or photo) and len(scope['department_titles'])==1:
                department = scope['department_titles'][0]
                directory_query = re.sub(r'(?<!\w)(?:зураг(?:тай|т)?|зург(?:ийг|аа|ийн)|хөрөг|photo|portrait)(?!\w)',' ',query,flags=re.I) if photo else query
                if _directory_only(directory_query, department):
                    selected = [row for row in rows if row['department']==department]
                    return dict(status='partial_directory', profiles=[self._card(row) for row in selected],
                        department=department, bundle_id=bundle,
                        candidates_scope='captured_profiles_only_not_full_staff_list')
            if _generic_staff_overview(query) and not re.search(r'зураг|хөрөг|photo|portrait', query, re.I):
                return dict(status='staff_scope_required', bundle_id=bundle, candidates=[],
                    candidates_scope='clarify_department_person_or_attribute')
        if not _overview_only(query, matches):
            return None
        if len(matches) > 1:
            return dict(status='ambiguous', candidates=[r['name'] for r in matches], bundle_id=bundle)
        if not matches and re.search(r'багш|teacher', query, re.I):
            # A generic photo chooser must not promise unavailable sample
            # portraits; a scoped directory can still disclose text-only rows.
            choices = [r for r in rows if r['image'] is not None] if re.search(
                r'зураг|зург|хөрөг|photo|portrait',query,re.I) else rows
            return dict(status='ambiguous', candidates=[r['name'] for r in choices], bundle_id=bundle,
                        candidates_scope='captured_profiles_only_not_full_staff_list')
        if len(matches) != 1:
            return None
        return dict(status='matched', profile=self._card(matches[0]), bundle_id=bundle)

    def attach(self, query, result):
        """Attach only when query AND answer AND exact capture citation agree.

        An old RAG page with the same URL but a different HTML hash is not proof
        of this newer teacher record, and receives no portrait automatically.
        """
        if not isinstance(result, dict) or result.get('route') not in ('A', 'B', 'C'):
            return []
        selected = self.profile(query)
        if not selected or selected['status'] != 'matched':
            return []
        card = selected['profile']
        if not card['portrait_available']:
            return []
        answer = result.get('answer', '')
        if not isinstance(answer, str) or not _contains(answer, card['name']):
            return []
        for citation in result.get('citations', []):
            if not isinstance(citation, dict):
                continue
            urls = [citation[k] for k in ('url', 'source_url_or_filename') if k in citation]
            hashes = [citation[k] for k in ('html_sha256', 'source_html_sha256') if k in citation]
            if (urls and hashes and all(url == card['source_url'] for url in urls) and
                all(value == card['source_html_sha256'] for value in hashes)):
                return [card]
        return []

    def media(self, media_id):
        if not isinstance(media_id, str) or not ID.fullmatch(media_id):
            raise KeyError('Unknown teacher media.')
        _, rows = self._load()
        for item in rows:
            asset = item['image']
            if asset and asset['media_id'] == media_id:
                data = _safe_file(self.root, asset['file'], MAX_IMAGE_BYTES)
                if _sha(data) != asset['sha256']:
                    raise TeacherMediaError('Teacher portrait changed during read.')
                return data, asset['mime']
        raise KeyError('Unknown teacher media.')
