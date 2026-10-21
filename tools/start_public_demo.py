"""Run a bounded public HTTPS trial through a protected loopback gateway.

This command creates a real public Cloudflare Quick Tunnel. Review the gateway
scope before running it. No installation, login, certificate trust or firewall
change is performed. All session secrets and logs stay under private runtime/.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PINNED_SHA256 = '4d2490e74082c5d48dbfedaf92576fa5bd1702379ab88eb7faa0cfbe8dc891b6'
URL_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')


def bounded_runtime_path(path):
    result = Path(path).resolve()
    if not result.is_relative_to((ROOT/'runtime').resolve()):
        raise ValueError('Private trial files must stay in the project runtime directory.')
    return result


def process_info(pid):
    """Read the executable and exact OS creation identity, not a recycled PID."""
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return None
        try:
            fields = [wintypes.FILETIME() for _ in range(4)]
            length = wintypes.DWORD(32768); name = ctypes.create_unicode_buffer(length.value)
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in fields]):
                raise OSError(ctypes.get_last_error(), 'Cannot inspect owned process creation time.')
            if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
                raise OSError(ctypes.get_last_error(), 'Cannot inspect owned process executable.')
            creation = (fields[0].dwHighDateTime << 32) | fields[0].dwLowDateTime
            return dict(pid=pid, creation_identity=str(creation), executable=str(Path(name.value).resolve()))
        finally: kernel.CloseHandle(handle)
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
        creation = stat[stat.rfind(')')+2:].split()[19]
        return dict(pid=pid, creation_identity=creation,
                    executable=str(Path(f'/proc/{pid}/exe').resolve()))
    except (FileNotFoundError, ProcessLookupError):
        return None


def validate_process_record(record):
    if not isinstance(record, dict) or set(record) != {'pid', 'creation_identity', 'executable', 'role'}:
        raise ValueError('Invalid owned process record.')
    if type(record['pid']) is not int or record['pid'] <= 0:
        raise ValueError('Invalid process ID.')
    if (not isinstance(record['creation_identity'], str) or not 1 <= len(record['creation_identity']) <= 64
            or not isinstance(record['executable'], str) or not Path(record['executable']).is_absolute()
            or record['role'] not in {'backend', 'gateway', 'tunnel'}):
        raise ValueError('Invalid process identity.')


def terminate_owned(record):
    """Terminate only a matching executable+creation identity through its handle."""
    validate_process_record(record)
    actual = process_info(record['pid'])
    if actual is None: return False
    if (actual['creation_identity'] != record['creation_identity']
            or Path(actual['executable']) != Path(record['executable'])):
        raise ValueError('Process identity changed; refuse to terminate a recycled PID.')
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        handle = kernel.OpenProcess(0x1001, False, record['pid'])
        if not handle: return False
        try:
            fields = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in fields]):
                raise OSError(ctypes.get_last_error(), 'Cannot recheck owned process identity.')
            creation = str((fields[0].dwHighDateTime << 32) | fields[0].dwLowDateTime)
            if creation != record['creation_identity']:
                raise ValueError('Process identity changed during stop; refuse recycled PID.')
            if not kernel.TerminateProcess(handle, 0):
                # An already exited process is harmless; never retry by PID.
                return False
            return True
        finally: kernel.CloseHandle(handle)
    import signal
    os.kill(record['pid'], signal.SIGTERM)
    return True


def python_command(script, *arguments):
    """Use the base executable directly so a Windows venv redirector cannot orphan children."""
    resolved_script = (ROOT/script).resolve()
    if not resolved_script.is_relative_to(ROOT):
        raise ValueError('Launch only project scripts.')
    packages = [str(Path(item).resolve()) for item in sys.path if 'site-packages' in item and Path(item).is_dir()]
    bootstrap = ('import runpy,site,sys;'
        + ''.join('site.addsitedir('+repr(item)+');' for item in packages)
        + 'sys.path.insert(0,'+repr(str(ROOT))+');sys.argv=sys.argv[1:];'
        + 'runpy.run_path(sys.argv[0],run_name="__main__")')
    binary = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
    return [str(binary), '-B', '-X', 'utf8', '-c', bootstrap, str(resolved_script), *map(str, arguments)]


def write_state(path, state):
    # This file includes the secret connect URL; callers must never publish it.
    temporary = path.with_name(path.name+'.'+secrets.token_hex(4)+'.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    temporary.replace(path)


def stop_session(path):
    directory = bounded_runtime_path(path)
    manifest = directory/'session.json'
    value = json.loads(manifest.read_text(encoding='utf-8'))
    if value.get('project_root') != str(ROOT) or value.get('session_dir') != str(directory):
        raise ValueError('Session root mismatch; no process was stopped.')
    records = value.get('owned_processes')
    if not isinstance(records, list) or not records:
        raise ValueError('Session has no owned process identities.')
    for row in records:
        validate_process_record(row)
        expected = process_info(row['pid'])
        if expected is not None and (expected['creation_identity'] != row.get('creation_identity')
                or expected['executable'] != row.get('executable')):
            raise ValueError('One process identity changed; no process was stopped.')
    stopped = []
    for row in reversed(records):
        if terminate_owned(row): stopped.append(row['role'])
    value.update(ready=False, stopped_utc=datetime.now(timezone.utc).isoformat(), stop_reason='explicit_stop',
                 stopped_roles=stopped)
    write_state(manifest, value)
    return directory


def request_backend_restart(path):
    """Private local control only; no public endpoint or extension of expiry."""
    directory = bounded_runtime_path(path)
    value = json.loads((directory/'session.json').read_text(encoding='utf-8'))
    if (value.get('project_root') != str(ROOT) or value.get('session_dir') != str(directory)
            or value.get('ready') is not True
            or datetime.fromisoformat(value['expires_utc']) <= datetime.now(timezone.utc)):
        raise ValueError('Only an active owned session can restart its backend.')
    records = value.get('owned_processes')
    if (not isinstance(records, list) or len(records) != 3
            or {row.get('role') for row in records if isinstance(row, dict)} != {'backend', 'gateway', 'tunnel'}):
        raise ValueError('Require all three active owned processes.')
    backend = None
    for record in records:
        validate_process_record(record)
        actual = process_info(record['pid'])
        if (actual is None or actual['creation_identity'] != record['creation_identity']
                or actual['executable'] != record['executable']):
            raise ValueError('An owned process changed; no restart was requested.')
        if record['role'] == 'backend': backend = record
    request = dict(requested_utc=datetime.now(timezone.utc).isoformat(),
        source='explicit_local_cli', expected_backend_creation_identity=backend['creation_identity'],
        expected_session_created_utc=value['created_utc'])
    marker = directory/'restart-backend.request.json'
    if marker.exists(): raise FileExistsError('A backend restart request is already pending.')
    write_state(marker, request)
    return directory


def consume_restart_request(directory, state):
    """Take one private marker, preserving rejected or completed requests on disk."""
    path = directory/'restart-backend.request.json'
    if not path.is_file(): return None
    try:
        request = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        path.replace(directory/('restart-request-'+secrets.token_hex(8)+'.rejected.json'))
        return None
    backend = next(row for row in state['owned_processes'] if row['role'] == 'backend')
    valid = (isinstance(request, dict)
        and set(request) == {'requested_utc', 'source', 'expected_backend_creation_identity', 'expected_session_created_utc'}
        and request['source'] == 'explicit_local_cli'
        and request['expected_backend_creation_identity'] == backend['creation_identity']
        and request['expected_session_created_utc'] == state['created_utc'])
    archive = directory/('restart-request-'+secrets.token_hex(8)+('.accepted.json' if valid else '.rejected.json'))
    path.replace(archive)
    return request if valid else None


def cleanup_owned_children(records, processes):
    """Retained Popen handles also clean up a child whose identity query failed."""
    failures = []
    for record in reversed(records):
        try:
            terminate_owned(record)
        except (ValueError, OSError) as error:
            failures.append(str(error))
    for process in processes:
        try:
            # On Windows these methods use Popen's original process handle, not
            # an untrusted or recycled PID read from a manifest.
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append(str(error))
    return failures


def log_released(path):
    """Windows process exit can precede the final inherited log-handle rundown."""
    if os.name != 'nt' or not path.exists(): return True
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # DELETE access verifies the same sharing permission that file cleanup
    # needs; metadata-only access does not reliably test deletion on Windows.
    handle = kernel.CreateFileW(str(path), 0x00010000, 7, None, 3, 128, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {32, 33}: return False
        raise OSError(error, 'Cannot verify released trial log.')
    kernel.CloseHandle(handle)
    return True


def wait_logs_released(paths, timeout=3):
    pending = list(paths)
    until = time.monotonic()+timeout
    while pending:
        pending = [path for path in pending if not log_released(path)]
        if not pending: return []
        if time.monotonic() >= until:
            return ['Owned process log is still in use after cleanup: '+str(path) for path in pending]
        time.sleep(0.025)
    return []


def run_trial(args):
    if type(args.lifetime) is not int or not 120 <= args.lifetime <= 7200:
        raise ValueError('A public session lasts120–7200seconds including tunnel startup.')
    if (type(args.backend_port) is not int or type(args.port) is not int
            or not 1 <= args.backend_port <= 65535 or not 1 <= args.port <= 65535
            or 8765 in {args.backend_port, args.port} or args.backend_port == args.port):
        raise ValueError('Use distinct trial ports and preserve the main8765 demo.')
    binary = bounded_runtime_path(args.cloudflared)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != PINNED_SHA256:
        raise ValueError('cloudflared differs from the verified official2026.10.1 Windowsamd64 release.')
    listening = bounded_runtime_path(args.listening_dir) if args.listening_dir else None
    if listening is not None:
        try:
            from tools.tts_listening_trial import ListeningTrial
        except ModuleNotFoundError:
            from tts_listening_trial import ListeningTrial
        ListeningTrial(listening)  # Validate all approved synthetic-school-text samples before exposure.
    for port in (args.backend_port, args.port):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    run_id = datetime.now(timezone.utc).strftime('run-%Y%m%dT%H%M%SZ-')+secrets.token_hex(4)
    directory = bounded_runtime_path(ROOT/'runtime/public-https'/run_id)
    directory.mkdir(parents=True, exist_ok=False)
    token_file = directory/'connect-token.txt'
    token = secrets.token_urlsafe(40)
    token_file.write_text(token+'\n', encoding='ascii', newline='\n')
    deadline = time.monotonic()+args.lifetime
    state = dict(project_root=str(ROOT), session_dir=str(directory), ready=False,
        created_utc=datetime.now(timezone.utc).isoformat(),
        expires_utc=datetime.fromtimestamp(time.time()+args.lifetime, timezone.utc).isoformat(),
        lifetime_seconds=args.lifetime, temporary=True, public_hosting_production=False,
        backend_port=args.backend_port, gateway_port=args.port, owned_processes=[],
        main_demo_unchanged=True, custom_certificate=False, firewall_changed=False,
        listening_dir=str(listening) if listening else None)
    state_file = directory/'session.json'
    write_state(state_file, state)
    processes = []
    streams = []
    def spawn(role, command, **kwargs):
        log = (directory/(role+'.log')).open('ab'); streams.append(log)
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs)
        processes.append(process)
        identity = process_info(process.pid)
        if identity is None: raise RuntimeError(role+' exited before process identity was recorded.')
        state['owned_processes'].append(dict(identity, role=role))
        write_state(state_file, state)
        return process
    def wait_status(url, seconds, process):
        wait_until = min(deadline, time.monotonic()+seconds)
        while time.monotonic() < wait_until:
            if process.poll() is not None: raise RuntimeError('Owned process exited during startup.')
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200: return
            except OSError:
                pass
            time.sleep(0.25)
        raise RuntimeError('Trial backend startup timed out.')
    reason = 'startup_failure'
    try:
        # The separate backend is never publicly routed: only the gateway is tunneled.
        backend = spawn('backend', python_command('demo_server.py', '--port', args.backend_port))
        wait_status(f'http://127.0.0.1:{args.backend_port}/api/status', 30, backend)
        command = [str(binary), 'tunnel', '--no-autoupdate', '--url',
                   f'http://127.0.0.1:{args.port}', '--metrics', '127.0.0.1:0', '--loglevel', 'info']
        if args.protocol == 'http2': command.extend(['--protocol', 'http2'])
        tunnel = spawn('tunnel', command)
        origin = None; until = min(deadline-60, time.monotonic()+60)
        while time.monotonic() < until:
            if tunnel.poll() is not None: raise RuntimeError('Cloudflare tunnel exited; see private tunnel.log.')
            text = (directory/'tunnel.log').read_text(encoding='utf-8', errors='replace')
            match = URL_PATTERN.search(text)
            if match:
                origin = match.group(); break
            time.sleep(0.25)
        if origin is None: raise RuntimeError('Cloudflare did not return a public HTTPS hostname within60seconds.')
        remaining = int(deadline-time.monotonic())
        gateway_args = ['--port', args.port, '--backend-port', args.backend_port,
            '--external-origin', origin, '--token-file', token_file, '--lifetime', remaining,
            '--result-dir', directory/'device-results']
        if listening: gateway_args.extend(['--listening-dir', listening])
        gateway = spawn('gateway', python_command('tools/serve_public_demo.py', *gateway_args))
        # Local ingress check uses the exact public Host; no secret is sent externally here.
        import http.client
        checked = False
        for _ in range(40):
            if gateway.poll() is not None: raise RuntimeError('Protected gateway exited during startup.')
            connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=2)
            try:
                connection.request('GET', '/api/status', headers={'Host': origin.removeprefix('https://')})
                response = connection.getresponse(); response.read()
                if response.status == 401: checked = True; break
            except OSError:
                pass
            finally: connection.close()
            time.sleep(0.25)
        if not checked: raise RuntimeError('Authentication rejection did not pass on local ingress.')
        state.update(ready=True, origin=origin, connect_url=origin+'/connect/'+token,
            device_check_url=origin+'/device-check', listening_url=origin+'/listening' if listening else None,
            local_ingress_unauthorized_status=401)
        write_state(state_file, state)
        print('Public HTTPS trial prepared. Private link: '+str(state_file), flush=True)
        reason = 'expired'
        while time.monotonic() < deadline:
            request = consume_restart_request(directory, state)
            if request is not None:
                reason = 'backend_restart_failure'
                record = next(row for row in state['owned_processes'] if row['role'] == 'backend')
                history = dict(request, previous_process=record,
                    started_utc=datetime.now(timezone.utc).isoformat(), completed=False,
                    expiry_extended=False)
                state.setdefault('backend_restart_history', []).append(history)
                state['backend_restarting'] = True; write_state(state_file, state)
                terminate_owned(record)
                backend.wait(timeout=5)
                state['owned_processes'].remove(record)
                processes.remove(backend)
                backend = spawn('backend', python_command('demo_server.py', '--port', args.backend_port))
                wait_status(f'http://127.0.0.1:{args.backend_port}/api/status', 30, backend)
                history.update(completed=True, completed_utc=datetime.now(timezone.utc).isoformat(),
                    current_process=next(row for row in state['owned_processes'] if row['role'] == 'backend'))
                state['backend_restarting'] = False; write_state(state_file, state)
                reason = 'expired'
            if any(process.poll() is not None for process in processes):
                reason = 'owned_process_exited'; break
            time.sleep(min(1, max(0, deadline-time.monotonic())))
    finally:
        failures = cleanup_owned_children(state['owned_processes'], processes)
        for stream in streams: stream.close()
        failures.extend(wait_logs_released([Path(stream.name) for stream in streams]))
        state.update(ready=False, stopped_utc=datetime.now(timezone.utc).isoformat(),
                     stop_reason=reason, cleanup_failures=failures)
        write_state(state_file, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloudflared', type=Path)
    parser.add_argument('--listening-dir', type=Path)
    parser.add_argument('--backend-port', type=int, default=8766)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--lifetime', type=int, default=7200)
    parser.add_argument('--protocol', choices=('auto', 'http2'), default='auto')
    control = parser.add_mutually_exclusive_group()
    control.add_argument('--stop', type=Path)
    control.add_argument('--restart-backend', type=Path)
    args = parser.parse_args()
    if args.stop:
        print('Stopped owned trial: '+str(stop_session(args.stop))); return
    if args.restart_backend:
        print('Requested owned backend restart: '+str(request_backend_restart(args.restart_backend))); return
    if args.cloudflared is None: parser.error('--cloudflared is required to start a public trial.')
    run_trial(args)


if __name__ == '__main__': main()
