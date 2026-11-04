"""Code map (/code-map) lists tracked Python files and local import edges, never file contents."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import code_map
import test_demo_server as server_fixture

FILES = {
    'server_app.py': '"""Serve the app."""\nimport rag_engine\nfrom tools import helper\nimport json\nSECRET = "do-not-leak"\n',
    'rag_engine.py': '"""Find sources for a question."""\nfrom voice_stt import listen\n',
    'voice_stt.py': '"""Turn speech into text."""\n',
    'tools/helper.py': 'import build_tree\n',
    'tools/build_tree.py': '"""Build the topic tree."""\n',
    'tests/test_server_app.py': 'import server_app\n',
    'broken.py': 'def (:\n',
}


class CodeMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name, text in FILES.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text, encoding='utf-8')
        (self.root / '.venv').mkdir()
        (self.root / '.venv/ignored.py').write_text('import os\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_edges_districts_and_guesses(self):
        result = code_map.scan(self.root)
        files = {item['path']: item for item in result['files']}
        self.assertNotIn('.venv/ignored.py', files)
        self.assertEqual(files['server_app.py']['imports'], ['rag_engine.py', 'tools/helper.py'])
        self.assertEqual(files['tools/helper.py']['imports'], ['tools/build_tree.py'])
        self.assertEqual(files['tests/test_server_app.py']['district'], 'Тестүүд')
        self.assertEqual(files['rag_engine.py']['workstream'], 'I')
        self.assertEqual(files['voice_stt.py']['workstream'], 'II')
        self.assertEqual(files['server_app.py']['workstream'], 'III')
        self.assertEqual(files['rag_engine.py']['doc'], 'Find sources for a question.')
        self.assertEqual(files['broken.py']['imports'], [])
        self.assertFalse(result['contents_included'])
        self.assertNotIn('do-not-leak', json.dumps(result))

    def test_edit_is_seen_on_next_scan(self):
        code_map.scan(self.root)
        (self.root / 'voice_stt.py').write_text('"""Changed purpose line."""\nimport rag_engine\n# longer\n', encoding='utf-8')
        files = {item['path']: item for item in code_map.scan(self.root)['files']}
        self.assertEqual(files['voice_stt.py']['doc'], 'Changed purpose line.')
        self.assertEqual(files['voice_stt.py']['imports'], ['rag_engine.py'])

    def test_git_tracked_files_are_preferred(self):
        try:
            subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True, capture_output=True, timeout=10)
            subprocess.run(['git', 'add', 'rag_engine.py'], cwd=self.root, check=True, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            self.skipTest('git is not available')
        self.assertEqual(code_map.tracked_python(self.root), ['rag_engine.py'])


class CodeMapHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper = server_fixture.DemoServerTests()
        self.helper.setUp()
        (self.helper.root / 'demo' / 'code-map.html').write_text('<html>Кодын хот</html>', encoding='utf-8')

    def tearDown(self):
        self.helper.tearDown()

    def test_page_and_api(self):
        status, body = self.helper.request('GET', '/code-map')
        self.assertEqual((status, body.decode('utf-8')), (200, '<html>Кодын хот</html>'))
        status, result = self.helper.request('GET', '/api/code-map')
        self.assertEqual(status, 200)
        self.assertFalse(result['contents_included'])
        self.assertEqual(self.helper.request('GET', '/api/code-map', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)


if __name__ == '__main__':
    unittest.main()
