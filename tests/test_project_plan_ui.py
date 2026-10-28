"""Weekly-plan interactions through real data.js in an isolated constructed DOM."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


class ProjectPlanUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for isolated UI checks.')
    def test_plan_progress_renderer_filters_safety_and_accessibility(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([shutil.which('node'), str(root/'tests/project_plan_ui_harness.js')],
                                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = json.loads(result.stdout)
        self.assertGreaterEqual(report['passed'], 12)
        self.assertTrue(report['constructed_fixtures'])
        self.assertFalse(report['browser_visual_qa'])
        self.assertEqual(report['model_calls'], 0)


if __name__ == '__main__':
    unittest.main()
