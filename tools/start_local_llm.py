"""Start the already-installed project-local Ollama, never install or pull models."""
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def start_local_llm(root):
    root=Path(root).resolve()
    config_path=root/'runtime/rag-model.json'
    try:
        config=json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('base_url','http://127.0.0.1:11434')!='http://127.0.0.1:11434':
            return False
    except (OSError,ValueError,AttributeError):
        return False
    runtime=root/'runtime/llm'
    binary=runtime/'ollama/ollama.exe'
    if not binary.is_file():
        return False
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:11434/api/version',timeout=.5) as response:
            return bool(json.loads(response.read(4096)).get('version'))
    except Exception:
        pass
    environment=os.environ.copy()
    environment.update(OLLAMA_HOST='127.0.0.1:11434',OLLAMA_MODELS=str(runtime/'models'),
                       OLLAMA_NO_CLOUD='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NUM_PARALLEL='1')
    with (runtime/'serve.stdout.log').open('ab') as out,(runtime/'serve.stderr.log').open('ab') as err:
        process=subprocess.Popen([str(binary),'serve'],cwd=runtime,env=environment,
            stdin=subprocess.DEVNULL,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (runtime/'serve.pid').write_text(str(process.pid),encoding='ascii')
    return True


if __name__=='__main__':
    print('Local LLM start attempted:',start_local_llm(Path(__file__).resolve().parent.parent))
