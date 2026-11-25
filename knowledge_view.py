"""The knowledge tree and the data behind it, shown beside the chat (2026-11-26).

The user, 11/26: «show our used knowledge tree on the right side; when a question is asked show the exact search
field — 11 sections divided into mini sections — so everyone can understand; and show all our data sets, everything
used in the knowledge tree and others».

Read-only, no search, no model, no change to any answer:

- tree():      the 11 domains (хүрээ) of config/knowledge-topics.json with their sub-sections (дэд хэсэг), and for
               each how many saved pages and page sections, stored answers and school-table rows it holds;
- datasets():  every data set the chat answers from, in plain words, with its size and the domains it feeds;
- place():     for one reply, the domain and sub-section it came from and from which data set; for a reply that
               found nothing, the domain the question named.

Pages, sections, stored answers and facts are placed by the tree's own rules (URL rules, fact rules, labelled
references — the same rules as tools/build_knowledge_tree.py); the school's tables by what they hold (rooms,
offices, staff, classes, timetable). Counts only: no person, e-mail or room list leaves this module.
"""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote, urlsplit

TOPICS_PATH = 'config/knowledge-topics.json'
DOMAINS_PATH = 'config/knowledge-domains.json'
SECTIONS_PATH = 'runtime/website-sections.json'
ROOT_TOPIC, REVIEW_TOPIC = 'nmct', 'review-needed'

# A reply from the school's tables: its reason code names what was looked up.
REASON_TOPICS = {
    'reception_person': 'staff.directory', 'reception_role_holder': 'staff.directory',
    'reception_role_list': 'staff.directory', 'reception_role_name': 'staff.directory',
    'reception_subject_teachers': 'staff.directory', 'reception_teacher_subjects': 'staff.directory',
    'reception_office_staff': 'staff.directory', 'reception_class_teacher': 'classes.groups',
    'reception_teacher_office': 'staff.offices', 'reception_teacher_office_unrecorded': 'staff.offices',
    'reception_teacher_meet': 'staff.offices', 'reception_role_meet': 'staff.offices', 'reception_role_room': 'staff.offices',
    'reception_teacher_email': 'staff.offices', 'reception_teacher_phone': 'staff.offices',
    'reception_role_email': 'staff.offices', 'reception_teacher_hours': 'staff.offices',
    'reception_subject_teacher_rooms': 'staff.offices', 'reception_class_teacher_room': 'classes.groups',
    'reception_class_teacher_email': 'classes.groups',
    'reception_teacher_day': 'staff.availability', 'reception_teacher_day_rooms': 'staff.availability',
    'reception_teacher_timetable': 'staff.availability',
    'reception_service_lookup': 'location.services', 'reception_service_exists': 'location.services',
    'reception_room_lookup': 'location.floors', 'reception_floor_rooms': 'location.floors',
    'reception_purpose_lookup': 'location.floors', 'reception_department_rooms': 'location.departments',
    'reception_class_room': 'classes.groups', 'reception_class_now': 'classes.timetable',
    'reception_class_day': 'classes.timetable', 'reception_class_week': 'classes.timetable',
    'reception_class_hours': 'classes.timetable', 'reception_school_hours': 'contact',
}
# The website's own teacher introductions, and fixed replies about the school itself.
KIND_TOPICS = {'official_teacher_profile': 'staff.directory', 'partial_teacher_directory': 'staff.directory',
               'school_website': 'contact'}
SOURCE_LABELS = {'table': 'Сургуулиас өгсөн хүснэгт', 'stored': 'Сайтын үгээр бэлдсэн хариулт',
                 'section': 'Сайтын хуудасны хэсэг', 'page': 'Сайтын хуудас', 'site': 'Сургуулийн вэб сайт'}


def url_topic(url, config):
    """The tree's URL rule: the longest explicit path wins; prefixes match whole path segments only."""
    fallback = config.get('fallback_topic_id', REVIEW_TOPIC)
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'nmct.edu.mn':
            return fallback
        path = unquote(parts.path).rstrip('/') or '/'
    except (ValueError, TypeError, AttributeError):
        return fallback
    matches = []
    for rule in config.get('url_rules', []):
        exact, prefix = rule.get('exact_path'), rule.get('path_prefix')
        if exact == path or (prefix is not None and (path == prefix or path.startswith(prefix.rstrip('/') + '/'))):
            matches.append((len(exact if exact is not None else prefix), exact is not None, rule['topic_id']))
    return max(matches)[2] if matches else fallback


def _path(url):
    try:
        return unquote(urlsplit(url).path).rstrip('/') or '/'
    except (ValueError, TypeError, AttributeError):
        return ''


class KnowledgeView:
    def __init__(self, root, website_database=None, content_database=None, tables=None):
        self.root = Path(root)
        self.config = json.loads((self.root / TOPICS_PATH).read_text(encoding='utf-8-sig'))
        try:
            domains = json.loads((self.root / DOMAINS_PATH).read_text(encoding='utf-8-sig')).get('domains', {})
        except (OSError, ValueError):
            domains = {}
        self.keywords = {key: [word.casefold() for word in value.get('keywords', [])] for key, value in domains.items()}
        self.topics = {topic['topic_id']: topic for topic in self.config['topics']}
        self.parent = {topic['topic_id']: topic.get('parent_id') for topic in self.config['topics']}
        self.counts = {identifier: Counter() for identifier in self.topics}
        self.sizes = Counter()
        self.as_of = ''
        self.faq_topics, self.fact_topics = {}, {}
        self._pages(website_database)
        self._sections()
        self._content(content_database)
        self._tables(tables)

    # -- placing the data -------------------------------------------------------------------------------------
    def domain_of(self, topic_id):
        current = topic_id
        while current is not None and self.parent.get(current) not in (ROOT_TOPIC, None):
            current = self.parent.get(current)
        return current if current in self.topics and current not in (ROOT_TOPIC, REVIEW_TOPIC) else None

    def _add(self, topic_id, kind, amount=1):
        if topic_id in self.counts:
            self.counts[topic_id][kind] += amount

    def _labelled(self, url, label, topic):
        """A labelled reference of the tree («Номын сан» on the environment page) names a sub-section."""
        for rule in self.config.get('source_reference_rules', []):
            if rule.get('exact_path') == _path(url) and rule.get('literal_label', '').casefold() == (label or '').casefold():
                return rule['topic_id']
        return topic

    def _pages(self, website_database):
        if website_database is None or not Path(website_database).is_file():
            return
        uri = 'file:' + Path(website_database).resolve().as_posix() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            rows = connection.execute('select p.url, max(p.version), max(p.retrieved_at) from pages p group by p.url').fetchall()
        for url, _, retrieved_at in rows:
            self._add(url_topic(url, self.config), 'pages')
            self.sizes['pages'] += 1
            if re.search(r'/(?:news|events)/', url or ''):
                self.sizes['news'] += 1
            self.as_of = max(self.as_of, str(retrieved_at or '')[:10])

    def _sections(self):
        try:
            data = json.loads((self.root / SECTIONS_PATH).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for section in data.get('sections', []):
            self._add(self._labelled(section.get('url'), section.get('heading'), url_topic(section.get('url'), self.config)),
                      'sections')
            self.sizes['sections'] += 1

    def _content(self, content_database):
        if content_database is None or not Path(content_database).is_file():
            return
        try:
            from sqlite_retrieval import ReadOnlyContentStore
            with ReadOnlyContentStore(Path(content_database)) as store:
                content = store.export(store.package_id())
        except Exception:
            return
        fallback = self.config.get('fallback_topic_id', REVIEW_TOPIC)
        sources = {(item['document_id'], item['version']): url_topic(item.get('source_url_or_filename'), self.config)
                   for item in content.get('sources', [])}

        def first_known(topics):
            return next((topic for topic in topics if topic != fallback), fallback)

        for fact in content.get('facts', []):
            refs = [sources.get((ref['document_id'], ref['version'])) for ref in fact.get('source_refs') or []]
            matches = [(len(prefix), rule['topic_id']) for rule in self.config.get('fact_rules', [])
                       if fact.get('entity_id') == rule['entity_id']
                       for prefix in rule['key_prefixes'] if (fact.get('key') or '').startswith(prefix)]
            self.fact_topics[fact['fact_id']] = max(matches)[1] if matches else first_known([t for t in refs if t])
            self._add(self.fact_topics[fact['fact_id']], 'facts')
        for faq in content.get('faqs', []):
            linked = [self.fact_topics[f] for f in faq.get('fact_ids') or [] if f in self.fact_topics]
            refs = [sources.get((ref['document_id'], ref['version'])) for ref in faq.get('source_refs') or []]
            self.faq_topics[faq['faq_id']] = first_known(linked + [t for t in refs if t])
            self._add(self.faq_topics[faq['faq_id']], 'answers')
        self.sizes.update(answers=len(content.get('faqs', [])), facts=len(content.get('facts', [])),
                          sources=len({item['document_id'] for item in content.get('sources', [])}))

    def _tables(self, tables):
        if tables is None:
            return
        rooms, staff = list(getattr(tables, 'rooms', ())), list(getattr(tables, 'staff', ()))
        classes, lessons = list(getattr(tables, 'classes', ())), list(getattr(tables, 'timetable', ()))
        services = [service for room in rooms for service in getattr(room, 'services', ())]
        self._add('location.floors', 'rows', len(rooms))
        self._add('location.services', 'rows', len(services))
        self._add('location.departments', 'rows', sum(1 for room in rooms if getattr(room, 'department', '')))
        self._add('staff.directory', 'rows', len(staff))
        self._add('staff.offices', 'rows', sum(1 for person in staff if getattr(person, 'room', '')))
        self._add('staff.availability', 'rows', len({getattr(lesson, 'teacher', '') for lesson in lessons} - {''}))
        self._add('classes.groups', 'rows', len(classes))
        self._add('classes.timetable', 'rows', len(lessons))
        self.sizes.update(rooms=len(rooms), services=len(services), staff=len(staff), classes=len(classes),
                          lessons=len(lessons))

    # -- views ----------------------------------------------------------------------------------------------------
    def _total(self, topic_id):
        total = Counter(self.counts.get(topic_id, ()))
        for child, parent in self.parent.items():
            if parent == topic_id:
                total.update(self._total(child))
        return total

    def tree(self):
        domains = []
        for identifier, topic in self.topics.items():
            if self.parent.get(identifier) != ROOT_TOPIC or identifier == REVIEW_TOPIC:
                continue
            children = [dict(id=child, label=self.topics[child]['label_mn'], counts=dict(self._total(child)))
                        for child, parent in self.parent.items() if parent == identifier]
            domains.append(dict(id=identifier, label=topic['label_mn'], counts=dict(self._total(identifier)),
                                children=children))
        return domains

    def datasets(self):
        """The data sets in plain words; the domains each one feeds."""
        def feeding(*kinds):
            return [domain['label'] for domain in self.tree() if any(domain['counts'].get(kind) for kind in kinds)]
        sizes = self.sizes
        sets = [dict(kind='site', title='Сургуулийн вэб сайт (nmct.edu.mn)',
                     lines=[f"{sizes['pages']} хуудас хадгалсан" + (f" ({self.as_of}-ны байдлаар)" if self.as_of else ''),
                            f"Үүнээс {sizes['news']} нь мэдээ, арга хэмжээ",
                            f"{sizes['sections']} гарчигтай хэсэгт хуваасан — «… гэж юу вэ?» асуултад бүтэн хэсгээр хариулна"],
                     feeds=feeding('pages', 'sections')),
                dict(kind='stored', title='Сайтын үгээр бэлдсэн асуулт, хариулт',
                     lines=[f"{sizes['answers']} хариулт, {sizes['facts']} баримт, {sizes['sources']} эх сурвалж",
                            'Хариулт бүрийн өгүүлбэрийг сайтын хуудаснаас үгчлэн авсан'],
                     feeds=feeding('answers', 'facts')),
                dict(kind='school', title='Сургуулиас өгсөн хүснэгт',
                     lines=[f"{sizes['rooms']} өрөө, үүнээс {sizes['services']} алба, үйлчилгээ",
                            f"{sizes['staff']} ажилтан (албан тушаал, ажлын өрөө, сургуулийн имэйл)",
                            f"{sizes['classes']} анги, {sizes['lessons']} мөр хичээлийн хуваарь"],
                     feeds=feeding('rows')),
                dict(kind='tree', title='Мэдлэгийн мод',
                     lines=[f"{len(self.tree())} хүрээ, {sum(len(d['children']) for d in self.tree())} дэд хэсэг",
                            'Асуулт бүрийг аль хүрээ, аль дэд хэсгээс хайхыг заана'],
                     feeds=[])]
        return [item for item in sets if item['kind'] == 'tree' or any(sizes[key] for key in (
            {'site': ('pages',), 'stored': ('answers',), 'school': ('rooms', 'staff')}[item['kind']]))]

    def asked(self, query):
        """The domains whose words the question uses."""
        text = (query or '').casefold()
        # At the start of a word: «анги» is also inside «сангийн».
        return [key for key, words in self.keywords.items() if key in self.topics
                and any(re.search(r'(?<!\w)' + re.escape(word), text) for word in words)]

    def _one(self, reason, kind, faq_id, urls, locators):
        """(topic, data set) of one answered reply, or (None, None)."""
        if reason in REASON_TOPICS or (reason or '').startswith('reception_'):
            topic = REASON_TOPICS.get(reason) or ('classes.timetable' if 'class' in (reason or '') or 'timetable' in (reason or '')
                                                  else 'location')
            return topic, 'table'
        if kind in KIND_TOPICS:
            return KIND_TOPICS[kind], 'site'
        if faq_id and faq_id in self.faq_topics:
            return self.faq_topics[faq_id], 'stored'
        for url in urls:
            topic = url_topic(url, self.config)
            if kind == 'website_section':
                topic = self._labelled(url, next(iter(locators), ''), topic)
            if topic != self.config.get('fallback_topic_id', REVIEW_TOPIC):
                return topic, ('section' if kind == 'website_section' else 'stored' if 'stored' in (reason or '') else 'page')
        return None, None

    def place(self, result, query=''):
        """Where one reply came from in the tree, in plain words."""
        if not isinstance(result, dict):
            return None
        parts = result.get('parts') or [dict(result, source_urls=[c.get('source_url_or_filename') for c in result.get('citations') or []],
                                             locators=[c.get('locator') for c in result.get('citations') or [] if c.get('locator')],
                                             answered=bool((result.get('answer') or '').strip()))]
        places, seen = [], set()
        for part in parts:
            if not part.get('answered', bool((part.get('answer') or '').strip())):
                continue
            topic, source = self._one(part.get('reason_code'), part.get('answer_kind'), part.get('answer_faq_id'),
                                      [url for url in part.get('source_urls') or [] if url], part.get('locators') or [])
            if topic is None or (topic, source) in seen:
                continue
            seen.add((topic, source))
            domain = self.domain_of(topic) or topic
            places.append(dict(domain_id=domain, domain=self.topics.get(domain, {}).get('label_mn', ''),
                               topic_id=topic if topic != domain else None,
                               topic=self.topics[topic]['label_mn'] if topic != domain and topic in self.topics else None,
                               source=source, source_label=SOURCE_LABELS.get(source, '')))
        asked = [dict(domain_id=key, domain=self.topics[key]['label_mn']) for key in self.asked(query or result.get('query'))]
        return dict(places=places, asked=asked, found=bool(places))
