"""Launcher checks never create an external tunnel."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import socket
import time
import unittest
from unittest.mock import patch

from tools import start_public_demo as launcher


@contextmanager
def temporary_supervisor_directory():
    """Retry only transient Windows delete-sharing races after process cleanup."""
    temporary = tempfile.TemporaryDirectory(prefix='public-supervisor-test-', dir=launcher.ROOT/'runtime')
    target = Path(temporary.name).resolve()
    if not target.is_relative_to((launcher.ROOT/'runtime').resolve()):
        raise ValueError('Supervisor fixture cleanup escaped project runtime.')
    try:
        yield str(target)
    finally:
        deadline = time.monotonic()+3
        while True:
            # Recheck the absolute target before each recursive native cleanup.
            if not Path(temporary.name).resolve().is_relative_to((launcher.ROOT/'runtime').resolve()):
                raise ValueError('Supervisor fixture cleanup path changed.')
            try:
                temporary.cleanup(); break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in {32, 33} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.025)


class PublicLauncherTests(unittest.TestCase):
    def setUp(self):
        # A fresh public checkout intentionally contains no private runtime tree.
        project = launcher.ROOT.resolve()
        runtime = (project/'runtime').resolve()
        if runtime.parent != project:
            raise ValueError('Synthetic fixture runtime escaped the project root.')
        runtime.mkdir(exist_ok=True)

    @unittest.skipUnless(os.name == 'nt', 'Windows delete-sharing semantics')
    def test_actual_open_log_delete_share_is_detected_and_release_is_verified(self):
        with tempfile.TemporaryDirectory(prefix='public-log-test-', dir=launcher.ROOT/'runtime') as folder:
            path = Path(folder)/'fixture.log'
            with path.open('wb') as stream:
                stream.write(b'fixture'); stream.flush()
                self.assertFalse(launcher.log_released(path))
            self.assertTrue(launcher.log_released(path))

    def test_log_rundown_is_bounded_and_unreleased_handle_is_not_hidden(self):
        path = launcher.ROOT/'runtime/owned-log-fixture.log'
        with patch.object(launcher, 'log_released', side_effect=[False, True]) as probe:
            self.assertEqual(launcher.wait_logs_released([path]), [])
            self.assertEqual(probe.call_count, 2)
        with patch.object(launcher, 'log_released', return_value=False):
            errors = launcher.wait_logs_released([path], timeout=0)
            self.assertEqual(len(errors), 1)
            self.assertIn('still in use', errors[0])

    def test_full_loopback_orchestration_expiry_stops_all_three_owned_processes(self):
        """A fake tunnel only prints a hostname; it makes no external connection."""
        with temporary_supervisor_directory() as folder:
            fixture = Path(folder).resolve()
            fake_binary = fixture/'not-a-tunnel.fixture'
            fake_binary.write_bytes(b'local orchestration fixture')
            session = fixture/'session'
            with socket.socket() as one, socket.socket() as two:
                one.bind(('127.0.0.1', 0)); two.bind(('127.0.0.1', 0))
                backend_port, gateway_port = one.getsockname()[1], two.getsockname()[1]
            args = argparse.Namespace(lifetime=120, backend_port=backend_port, port=gateway_port,
                cloudflared=fake_binary, listening_dir=None, protocol='auto')
            actual_popen = subprocess.Popen
            actual_bounds = launcher.bounded_runtime_path
            actual_clock = time.monotonic
            base_python = str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
            children = []
            def spawn(command, **kwargs):
                if command[0] == str(fake_binary):
                    command = [base_python, '-u', '-c',
                        'import time; print("https://local-fixture.trycloudflare.com",flush=True); time.sleep(60)']
                elif str(launcher.ROOT/'demo_server.py') in command:
                    program = ('from http.server import BaseHTTPRequestHandler,HTTPServer\n'
                        'class H(BaseHTTPRequestHandler):\n'
                        ' def log_message(self,*args): pass\n'
                        ' def do_GET(self):\n'
                        '  self.send_response(200); self.send_header("Content-Length","2"); self.end_headers(); self.wfile.write(b"{}")\n'
                        f'HTTPServer(("127.0.0.1",{backend_port}),H).serve_forever()\n')
                    command = [base_python, '-u', '-c', program]
                child = actual_popen(command, **kwargs); children.append(child); return child
            def bounds(path):
                result = actual_bounds(path)
                return session if result.parent == launcher.ROOT/'runtime/public-https' else result
            def clock():
                path = session/'session.json'
                if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('ready'):
                    return actual_clock()+1000  # Simulate expiry after readiness, never a public tunnel.
                return actual_clock()
            with patch.object(launcher, 'PINNED_SHA256', hashlib.sha256(fake_binary.read_bytes()).hexdigest()):
                with patch.object(launcher, 'bounded_runtime_path', side_effect=bounds):
                    with patch.object(launcher.subprocess, 'Popen', side_effect=spawn):
                        with patch.object(launcher.time, 'monotonic', side_effect=clock):
                            launcher.run_trial(args)
            final = json.loads((session/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(len(children), 3)
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertEqual(final['stop_reason'], 'expired')
            self.assertFalse(final['ready'])
            self.assertEqual(final['cleanup_failures'], [])
            self.assertEqual(final['local_ingress_unauthorized_status'], 401)

    def test_restart_is_private_identity_bound_one_shot_and_does_not_extend_expiry(self):
        with tempfile.TemporaryDirectory(prefix='public-restart-test-', dir=launcher.ROOT/'runtime') as folder:
            root = Path(folder).resolve()
            exe = str(Path(sys.executable).resolve())
            records = [dict(pid=100001+i, creation_identity='fixture-'+role, executable=exe, role=role)
                       for i, role in enumerate(('backend', 'gateway', 'tunnel'))]
            expiry = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
            value = dict(project_root=str(launcher.ROOT), session_dir=str(root), ready=True,
                created_utc='fixture-session-time', expires_utc=expiry, owned_processes=records)
            launcher.write_state(root/'session.json', value)
            def info(pid):
                row = next(item for item in records if item['pid'] == pid)
                return {key: row[key] for key in ('pid', 'creation_identity', 'executable')}
            with patch.object(launcher, 'process_info', side_effect=info):
                self.assertEqual(launcher.request_backend_restart(root), root)
                with self.assertRaises(FileExistsError): launcher.request_backend_restart(root)
            self.assertEqual(json.loads((root/'session.json').read_text())['expires_utc'], expiry)
            request = launcher.consume_restart_request(root, value)
            self.assertEqual(request['source'], 'explicit_local_cli')
            self.assertIsNone(launcher.consume_restart_request(root, value))
            launcher.write_state(root/'restart-backend.request.json', dict(request,
                expected_backend_creation_identity='recycled-fixture'))
            self.assertIsNone(launcher.consume_restart_request(root, value))
            (root/'restart-backend.request.json').write_bytes(b'{"partial":')
            self.assertIsNone(launcher.consume_restart_request(root, value))
            self.assertEqual(len(list(root.glob('*.accepted.json'))), 1)
            self.assertEqual(len(list(root.glob('*.rejected.json'))), 2)
            value['expires_utc'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            launcher.write_state(root/'session.json', value)
            with self.assertRaises(ValueError): launcher.request_backend_restart(root)

    def test_runtime_and_script_bounds_are_checked(self):
        with self.assertRaises(ValueError): launcher.bounded_runtime_path(launcher.ROOT/'README.md')
        with self.assertRaises(ValueError): launcher.bounded_runtime_path(launcher.ROOT/'runtime/../../escape')
        with self.assertRaises(ValueError): launcher.python_command('../escape.py')
        self.assertEqual(launcher.bounded_runtime_path(launcher.ROOT/'runtime/public-https'),
                         launcher.ROOT/'runtime/public-https')

    def test_direct_base_python_preserves_project_imports_without_redirector(self):
        command = launcher.python_command('tools/serve_public_demo.py', '--help')
        self.assertEqual(Path(command[0]), Path(getattr(sys, '_base_executable', sys.executable)).resolve())
        result = subprocess.run(command, cwd=launcher.ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--external-origin', result.stdout)

    def test_unsafe_lifetimes_ports_and_wrong_vendor_binary_stop_before_spawn(self):
        base = dict(lifetime=120, backend_port=8766, port=8787,
                    cloudflared=launcher.ROOT/'runtime/nonexistent-fixture.exe', listening_dir=None)
        for changed in ({'lifetime': 7201}, {'lifetime': True}, {'lifetime': 60},
                        {'backend_port': 8765}, {'port': 8765}, {'port': 8766}):
            with self.subTest(changed=changed), patch.object(launcher.subprocess, 'Popen') as spawn:
                with self.assertRaises(ValueError): launcher.run_trial(argparse.Namespace(**dict(base, **changed)))
                spawn.assert_not_called()
        with patch.object(Path, 'read_bytes', return_value=b'wrong vendor binary'):
            with patch.object(launcher.subprocess, 'Popen') as spawn:
                with self.assertRaises(ValueError): launcher.run_trial(argparse.Namespace(**base))
                spawn.assert_not_called()

    def test_creation_identity_protects_recycled_pid_and_real_owned_child_is_stopped(self):
        child = subprocess.Popen([str(Path(getattr(sys, '_base_executable', sys.executable)).resolve()),
            '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            info = launcher.process_info(child.pid)
            self.assertIsNotNone(info)
            record = dict(info, role='backend')
            with self.assertRaises(ValueError):
                launcher.terminate_owned(dict(record, creation_identity='recycled-fixture'))
            self.assertIsNone(child.poll())
            self.assertTrue(launcher.terminate_owned(record))
            child.wait(timeout=5)
            self.assertIsNotNone(child.returncode)
        finally:
            if child.poll() is None: child.terminate(); child.wait(timeout=5)

    def test_retained_handle_cleans_up_owned_child_even_when_identity_capture_failed(self):
        child = subprocess.Popen([str(Path(getattr(sys, '_base_executable', sys.executable)).resolve()),
            '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            # No identity was successfully recorded: only the actual Popen handle is available.
            self.assertEqual(launcher.cleanup_owned_children([], [child]), [])
            self.assertIsNotNone(child.returncode)
        finally:
            if child.poll() is None: child.terminate(); child.wait(timeout=5)

    def test_stop_checks_entire_session_before_mutating_any_owned_process(self):
        parent = launcher.ROOT/'runtime'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='public-launcher-test-', dir=parent) as folder:
            root = Path(folder).resolve()
            fixture_exe = str(Path(sys.executable).resolve())
            records = [dict(pid=100001, creation_identity='fixture-one', executable=fixture_exe, role='backend'),
                       dict(pid=100002, creation_identity='fixture-two', executable=fixture_exe, role='tunnel')]
            value = dict(project_root=str(launcher.ROOT), session_dir=str(root), owned_processes=records)
            launcher.write_state(root/'session.json', value)
            def info(pid):
                return dict(pid=pid, creation_identity='fixture-one' if pid == 100001 else 'recycled',
                            executable=fixture_exe)
            with patch.object(launcher, 'process_info', side_effect=info):
                with patch.object(launcher, 'terminate_owned') as terminate:
                    with self.assertRaises(ValueError): launcher.stop_session(root)
                    terminate.assert_not_called()
            with patch.object(launcher, 'process_info', return_value=None):
                with patch.object(launcher, 'terminate_owned', return_value=False):
                    self.assertEqual(launcher.stop_session(root), root)
            final = json.loads((root/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(final['stop_reason'], 'explicit_stop')
            self.assertFalse(final['ready'])


if __name__ == '__main__': unittest.main()
