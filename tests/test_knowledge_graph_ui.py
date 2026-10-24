"""UI graph topology and interaction checks; no browser/visual QA claim."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


class KnowledgeGraphUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for isolated UI checks.')
    def test_public_topic_graph_topology_accessibility_and_interactions(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([shutil.which('node'), str(root/'tests/knowledge_graph_ui_harness.js')],
            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertGreaterEqual(report['passed'], 12)
        self.assertEqual(report['counts'], dict(topics=33,topic_edges=32,processing_nodes=16,processing_edges=19))


if __name__ == '__main__':
    unittest.main()
