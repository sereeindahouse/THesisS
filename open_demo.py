"""Open the loopback thesis demo, starting its server only when necessary."""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


def probe_demo(port=PORT, *, timeout=2.5):
    """Return our status, None for an unused port; reject an unrelated service."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except (ConnectionRefusedError, TimeoutError):
        return None
    except OSError as error:
        raise RuntimeError(f"{port} портыг шалгаж чадсангүй: {error}") from error
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError("unexpected response")
            payload = response.read(65537)
            if len(payload) > 65536:
                raise ValueError("status response too large")
            status = json.loads(payload)
        expected = (
            isinstance(status, dict)
            and status.get("mode") == "local_development"
            and (status.get("content_database_readonly") is True or status.get("readonly") is True)
            and status.get("generated") is False
            and type(status.get("llm_calls")) is int and status["llm_calls"] == 0
            and isinstance(status.get("content"), dict)
            and isinstance(status.get("retrieval"), dict)
            and status["retrieval"].get("live_backend") in ("bm25", "bm25_mongolian", "bm25+e5_rrf")
        )
        if not expected:
            raise ValueError("unexpected demo identity")
        return status
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise RuntimeError(
            f"{port} порт дээр өөр үйлчилгээ эсвэл танигдахгүй сервер байна. "
            "Одоо ажиллаж буй процессыг зогсоосонгүй. "
            "Портын хэрэглээг нягтлаад DEMO.cmd-ийг дахин нээнэ үү."
        ) from error


def ensure_database(root):
    """Create a missing development DB atomically; never replace an existing DB."""
    database = root / "runtime" / "content.db"
    if database.exists():
        if not database.is_file():
            raise RuntimeError(f"Өгөгдлийн сангийн зам файл биш: {database}")
        return False
    source = root / "data" / "content-draft-v1.json"
    importer = root / "import_content.py"
    if not source.is_file() or not importer.is_file():
        raise RuntimeError("data/content-draft-v1.json эсвэл import_content.py олдсонгүй.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="demo-import-", dir=database.parent) as temporary:
        staged = Path(temporary) / "content.db"
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(importer), "--db", str(staged),
             "import", str(source), "--allow-draft"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Draft агуулгыг импортолж чадсангүй: {detail}")
        try:
            # A hard link on the same filesystem creates the final name exclusively.
            os.link(staged, database)
        except FileExistsError:
            return False
    return True


def start_or_reuse(root=ROOT, *, port=PORT):
    root = Path(root).resolve()
    for required in ("demo_server.py", "demo/index.html"):
        if not (root / required).is_file():
            raise RuntimeError(f"{required} олдсонгүй. DEMO.cmd-ийг төслийн үндсэн хавтаснаас нээнэ үү.")
    status = probe_demo(port)
    created_database = ensure_database(root)
    if created_database:
        print("Draft агуулгыг SQLite-д импортлов; сургуулиар батлагдсан агуулга болоогүй.")
    if status is not None:
        status = probe_demo(port)
        if status is None or not status["content"].get("available"):
            raise RuntimeError("Demo ажиллаж байгаа ч SQLite агуулгыг уншиж чадсангүй. Байгаа санг өөрчлөөгүй.")
        return {"url": f"http://127.0.0.1:{port}", "reused_server": True, "database_created": created_database}
    # Prefer the existing combined embedding/voice environment when complete.
    python = sys.executable
    candidate = root / ".venv-modeltools/Scripts/python.exe"
    if candidate.is_file():
        checked = subprocess.run([str(candidate), "-c",
            "import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(x) for x in ('torch','transformers','faster_whisper','edge_tts')))"] ,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if checked.returncode == 0:
            python = str(candidate)
    from tools.start_local_llm import start_local_llm
    start_local_llm(root)
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "demo-server.stdout.log").open("ab") as output, \
            (runtime / "demo-server.stderr.log").open("ab") as errors:
        process = subprocess.Popen(
            [python, "-X", "utf8", str(root / "demo_server.py"), "--port", str(port)],
            cwd=root, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status = probe_demo(port, timeout=min(2.5, remaining / 2))
            if status is not None:
                if not status["content"].get("available"):
                    raise RuntimeError("Сервер эхэлсэн ч SQLite агуулга уншигдсангүй.")
                # Only record a PID that still belongs to our own running child.
                if process.poll() is None:
                    (runtime / "demo-server.pid").write_text(str(process.pid) + "\n", encoding="ascii")
                return {"url": f"http://127.0.0.1:{port}", "reused_server": False, "database_created": created_database}
            if process.poll() is not None:
                raise RuntimeError("Demo сервер эхлэхэд алдаа гарлаа. runtime/demo-server.stderr.log-ийг харна уу.")
            time.sleep(min(0.15, max(0, deadline - time.monotonic())))
        raise RuntimeError("Demo сервер 8 секундэд бэлэн болсонгүй. runtime/demo-server.stderr.log-ийг харна уу.")
    except Exception:
        if process.poll() is None:
            process.terminate()  # Only our newly started child; never an unrelated service.
        raise


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 буюу түүнээс шинэ хувилбар шаардлагатай.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Дипломын локал demo-г браузерт нээх")
    parser.add_argument("--no-browser", action="store_true", help="Серверийг шалгаж, браузер нээхгүй")
    parser.add_argument("--data", action="store_true", help="Эхийн сан ба төслийн явцыг нээх")
    args = parser.parse_args()
    try:
        result = start_or_reuse()
        print("Ажиллаж буй demo-г дахин ашиглав." if result["reused_server"] else "Demo серверийг эхлүүлэв.")
        print(f"Demo: {result['url']}")
        browser_url = result["url"] + ("/data" if args.data else "")
        if not args.no_browser and not webbrowser.open(browser_url, new=2):
            print("Браузер автоматаар нээгдсэнгүй. Дээрх хаягийг браузерт нээнэ үү.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Алдаа: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
