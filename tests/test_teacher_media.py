import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from teacher_media import TeacherMedia, TeacherMediaError


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6qSMAAAAASUVORK5CYII=')


def sha(value):
    return hashlib.sha256(value).hexdigest()


class TeacherMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / 'media'
        (self.store / 'images').mkdir(parents=True)
        self.teacher = dict(id=1, name='Батчулуун', nameEn='Batchuluun', position='Багш',
                            bio='Компьютерийн ухааны багш', image='/uploads/teacher.png')
        self.write_fixture([self.teacher])
        self.manager = TeacherMedia(self.root, self.store / 'manifest.json')

    def write_fixture(self, teachers):
        payload = {'teachers': teachers}
        stream = '4:' + json.dumps(payload, ensure_ascii=False) + '\n'
        html = ('<html><head><title>Компьютерын ухааны тэнхим | NMCT</title></head><body>'
                '<script>self.__next_f.push(' + json.dumps([1, stream], ensure_ascii=False) + ')</script></body></html>').encode('utf8')
        (self.store / 'page.html').write_bytes(html)
        self.manifest = dict(schema_version=1, method='explicit_official_next_flight_teacher_record', profiles=[])
        for index, teacher in enumerate(teachers):
            image = PNG if index == 0 else PNG + b'different fixture bytes'
            digest = sha(image)
            path = 'images/' + digest + '.png'
            (self.store / path).write_bytes(image)
            row = dict(teacher_id='nmct-computer-science-' + str(teacher['id']),
                name=teacher['name'], aliases=[teacher['name'], teacher['nameEn']],
                role=teacher['position'], bio=teacher['bio'], department='Компьютерын ухааны тэнхим',
                source=dict(url='https://nmct.edu.mn/departments/computer-science',
                    captured_utc='2026-10-21T04:06:00+00:00', html_file='page.html', html_sha256=sha(html),
                    record='4', pointer='/teachers/' + str(index),
                    teacher_record_sha256=sha(json.dumps(teacher,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())),
                image=dict(media_id='teacher-' + digest[:24], file=path,
                    url='https://nmct.edu.mn' + teacher['image'], mime='image/png', sha256=digest,
                    bytes=len(image), width=1, height=1))
            self.manifest['profiles'].append(row)
        self.save()

    def save(self):
        (self.store / 'manifest.json').write_text(json.dumps(self.manifest,ensure_ascii=False),encoding='utf8')

    def test_named_profile_has_exact_fields_and_safe_asset_url(self):
        result = self.manager.profile('Батчулуун багшийн зураг харуулна уу?')
        self.assertEqual(result['status'], 'matched')
        card = result['profile']
        self.assertEqual(card['name'], self.teacher['name'])
        self.assertEqual(card['source_fields']['bio'], self.teacher['bio'])
        self.assertTrue(card['image_url'].startswith('/api/teacher-media/teacher-'))
        self.assertNotIn(str(self.root), json.dumps(card,ensure_ascii=False))
        self.assertEqual(self.manager.media(card['media_id']), (PNG,'image/png'))

    def test_case_suffix_and_english_name_are_bounded(self):
        self.assertIsNotNone(self.manager.profile('Батчулууны тухай танилцуулна уу?'))
        self.assertIsNotNone(self.manager.profile('Please show me Batchuluun photo'))
        self.assertIsNone(self.manager.profile('ИхБатчулуун багшийн зураг'))
        self.assertIsNone(self.manager.profile('Batchuluunx photo'))

    def test_unsupported_fields_and_multi_intent_are_never_bio_fallback(self):
        for question in ['утасны дугаар', 'цалин', 'дансны мэдээлэл', 'гэрийн хаяг',
                         'хэдэн настай', 'ямар хичээл заадаг', 'маргаашийн хуваарь',
                         'судалгааны тухай мэдээлэл', 'зураг болон утас', 'зураг бүү харуул']:
            with self.subTest(question=question):
                self.assertIsNone(self.manager.profile('Батчулуун багшийн ' + question))

    def test_unknown_teacher_and_generic_request_are_not_random_portrait(self):
        for query in ['Дорж багшийн зураг', 'Батчулуун Дорж багшийн зураг']:
            self.assertIsNone(self.manager.profile(query))
        for query in ['Багш нарын зураг', 'Багшийн зурагтай танилцуулга үзье.']:
            result=self.manager.profile(query)
            self.assertEqual(result['status'],'ambiguous')
            self.assertEqual(result['candidates'],['Батчулуун'])
            self.assertEqual(result['candidates_scope'],'captured_profiles_only_not_full_staff_list')

    def test_named_two_profiles_requires_clarification(self):
        other = dict(self.teacher, id=2,name='Соронзонболд',nameEn='Soronzonbold',image='/uploads/second.png')
        self.write_fixture([self.teacher,other])
        # Distinct real PNG bytes with an ancillary text chunk are unnecessary
        # here: two references to one photo are deliberately rejected separately.
        # Make the second signature valid by using another valid color PNG.
        second_png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/l5s1hAAAAABJRU5ErkJggg==')
        row=self.manifest['profiles'][1];digest=sha(second_png)
        row['image'].update(media_id='teacher-'+digest[:24],file='images/'+digest+'.png',sha256=digest,bytes=len(second_png))
        (self.store/row['image']['file']).write_bytes(second_png);self.save()
        result=self.manager.profile('Батчулуун болон Соронзонболд багшийн зураг')
        self.assertEqual(result['status'],'ambiguous')
        self.assertEqual(set(result['candidates']),{'Батчулуун','Соронзонболд'})

    def test_scoped_staff_names_return_only_verified_partial_directory(self):
        for q in ['Компьютерийн багш нар хэн хэн байдаг вэ?',
                  'Компьютерын ухааны тэнхимийн багш нарын нэрийг хэлнэ үү.',
                  'Компьютерын ухааны багш нарын нэрсийг жагсааж өгөөч.',
                  'Компьютерийн багш нарын нэрсийг жагсаагаад өгөөч.',
                  'Компьютерын ухааны багш нарын нэрсийг харуулна уу.',
                  'Компьютерийн багш нарын зургийг харуулна уу.']:
            result=self.manager.profile(q)
            self.assertIsNotNone(result,q)
            self.assertEqual(result['status'],'partial_directory',q)
            self.assertEqual([card['name'] for card in result['profiles']],['Батчулуун'])
            self.assertEqual(result['candidates_scope'],'captured_profiles_only_not_full_staff_list')
        for q in ['Химийн багш нарын нэрийг хэлнэ үү.',
                  'Компьютерийн болон химийн багш нарын нэрийг хэлнэ үү.',
                  'Компьютерийн багш хэд вэ, нэрсийг хэлнэ үү.',
                  'Компьютерийн Дорж багшийн нэрийг хэлнэ үү.']:
            self.assertIsNone(self.manager.profile(q),q)

    def test_generic_staff_overview_asks_scope_without_forcing_photo(self):
        for q in ['Багш нарын талаар мэдээлэл өгөөч.',
                  'Багш нарынхаа талаар мэдээлэл өгөөч.','Багш нар']:
            result=self.manager.profile(q)
            self.assertEqual(result['status'],'staff_scope_required',q)
            self.assertEqual(result['candidates'],[])

    def test_attach_requires_matching_person_and_exact_capture(self):
        p=self.manifest['profiles'][0]
        result=dict(route='C',answer='Батчулуун — Багш',citations=[dict(url=p['source']['url'],html_sha256=p['source']['html_sha256'])])
        self.assertEqual(len(self.manager.attach('Батчулуун багшийн тухай',result)),1)
        canonical=dict(result,citations=[dict(source_url_or_filename=p['source']['url'],source_html_sha256=p['source']['html_sha256'])])
        self.assertEqual(len(self.manager.attach('Батчулуун багшийн тухай',canonical)),1)
        for changes in [dict(answer='Соронзонболд — Багш'),dict(route='D'),dict(citations=[]),
                        dict(citations=[dict(url=p['source']['url'],html_sha256='0'*64)]),
                        dict(citations=[dict(url=p['source']['url'],html_sha256=p['source']['html_sha256'],source_html_sha256='0'*64)]),
                        dict(citations=[dict(url='https://nmct.edu.mn/about',html_sha256=p['source']['html_sha256'])])]:
            self.assertEqual(self.manager.attach('Батчулуун багшийн тухай',dict(result,**changes)),[])

    def test_tampered_portrait_fails_after_cached_success(self):
        self.assertTrue(self.manager.status()['available'])
        path=self.store/self.manifest['profiles'][0]['image']['file']
        raw=bytearray(path.read_bytes());raw[25]^=1;path.write_bytes(raw)
        self.assertFalse(self.manager.status()['available'])
        self.assertIsNone(self.manager.profile('Батчулуун багшийн зураг'))
        with self.assertRaises(TeacherMediaError):self.manager.media(self.manifest['profiles'][0]['image']['media_id'])

    def test_tampered_html_fails_even_if_portrait_unchanged(self):
        self.assertTrue(self.manager.status()['available'])
        (self.store/'page.html').write_bytes(b'<html>different page</html>')
        self.assertFalse(self.manager.status()['available'])

    def test_wrong_teacher_object_binding_is_rejected(self):
        for field,value in [('name','Дорж'),('role','Захирал'),('bio','Invented biography'),
                            ('aliases',['Батчулуун','Дорж']),('department','Химийн тэнхим'),
                            ('teacher_id','nmct-computer-science-900')]:
            original=deepcopy(self.manifest)
            self.manifest['profiles'][0][field]=value;self.save()
            self.assertFalse(self.manager.status()['available'],field)
            self.manifest=original;self.save()

    def test_mime_forgery_and_svg_rejected(self):
        for mime in ['image/jpeg','image/svg+xml','text/html']:
            self.manifest['profiles'][0]['image']['mime']=mime;self.save()
            self.assertFalse(self.manager.status()['available'])

    def test_image_and_capture_path_escape_rejected(self):
        for path in ['../outside.png','/outside.png','C:/outside.png','images\\outside.png']:
            for section,field in [('image','file'),('source','html_file')]:
                original=deepcopy(self.manifest)
                self.manifest['profiles'][0][section][field]=path;self.save()
                self.assertFalse(self.manager.status()['available'])
                self.manifest=original;self.save()

    def test_external_source_hosts_ports_queries_and_placeholders_rejected(self):
        for url in ['https://evil.example/uploads/a.png','http://nmct.edu.mn/uploads/a.png',
                    'https://nmct.edu.mn:443/uploads/teacher.png','https://nmct.edu.mn/uploads/teacher.png?x=1',
                    'https://nmct.edu.mn/uploads/sample-woman.png']:
            original=deepcopy(self.manifest)
            self.manifest['profiles'][0]['image']['url']=url;self.save()
            self.assertFalse(self.manager.status()['available'])
            self.manifest=original;self.save()

    def test_unknown_and_traversal_ids_do_not_read_paths(self):
        for mid in ['../page.html','teacher-'+'a'*24,'https://nmct.edu.mn/uploads/a.png',None]:
            with self.assertRaises(KeyError):self.manager.media(mid)

    def test_missing_optional_store_disables_media(self):
        empty=TeacherMedia(self.root,self.root/'missing.json')
        self.assertFalse(empty.status()['available'])
        self.assertEqual(empty.catalog(),[])
        self.assertIsNone(empty.profile('Батчулуун багшийн зураг'))

    def test_catalog_returns_copies_and_bundle_changes_on_manifest_edit(self):
        initial=self.manager.status()['bundle_id']
        cards=self.manager.catalog();cards[0]['name']='Bad edit'
        self.assertEqual(self.manager.catalog()[0]['name'],'Батчулуун')
        self.manifest['operator_note']='a new manifest version';self.save()
        self.assertNotEqual(self.manager.status()['bundle_id'],initial)

    def test_manifest_outside_project_rejected(self):
        with self.assertRaises(TeacherMediaError):TeacherMedia(self.store,self.root/'outside.json')

    def test_malformed_manifest_fields_disable_optional_feature(self):
        for field,value in [('name',{}),('department',None),('bio',[]),('teacher_id',False)]:
            original=deepcopy(self.manifest)
            self.manifest['profiles'][0][field]=value;self.save()
            self.assertFalse(self.manager.status()['available'])
            self.assertEqual(self.manager.catalog(),[])
            self.manifest=original;self.save()

    def test_hash_id_dimensions_and_record_pointer_tampering_rejected(self):
        for section,field,value in [('image','media_id','teacher-'+'0'*24),
                                    ('image','width',500),('image','sha256','0'*64),
                                    ('source','pointer','/teachers/2'),
                                    ('source','captured_utc','invalid+00:00')]:
            original=deepcopy(self.manifest)
            self.manifest['profiles'][0][section][field]=value;self.save()
            self.assertFalse(self.manager.status()['available'],field)
            self.manifest=original;self.save()


if __name__=='__main__':unittest.main()
