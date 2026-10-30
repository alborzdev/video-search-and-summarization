"""Fixed operator control for the optional, cached embedding service."""
import json
from pathlib import Path
import subprocess
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[2]

class EmbeddingControl:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False
        self.error = ''

    def status(self):
        result = subprocess.run(['docker', 'inspect', 'vss-rtvi-embed', '--format', '{{json .State.Running}}'], capture_output=True, text=True, timeout=5)
        running = result.returncode == 0 and result.stdout.strip() == 'true'
        ready = False
        if running:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8017/v1/ready', timeout=2) as response:
                    ready = response.status == 200
            except OSError:
                pass
        return {'schemaVersion':'city.embedding-control.v1','running':running,'ready':ready,'busy':self.busy,'error':self.error,'startupEnabled':False}

    def action(self, operation):
        if operation not in ('start','stop'):
            raise ValueError('Choose start or stop embeddings')
        with self.lock:
            if self.busy:
                return self.status()
            self.busy = True
            self.error = ''
        def work():
            try:
                settings = json.loads((ROOT/'.spark/settings.json').read_text())
                available = next(int(line.split()[1])/1024**2 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                if operation == 'start' and available < float(settings.get('reserve_gib',0)):
                    raise RuntimeError('The selected memory reserve is not available')
                command = ['docker','compose','-f',str(ROOT/'.spark/compose.json')]
                command += ['up','-d','--no-deps','--no-build','--pull','never','rtvi-embed'] if operation == 'start' else ['stop','rtvi-embed']
                result = subprocess.run(command,capture_output=True,text=True,timeout=90)
                if result.returncode:
                    raise RuntimeError('Embedding service could not '+operation+'. Check the local service logs.')
            except Exception as error:
                self.error = str(error)[:300]
            finally:
                self.busy = False
        threading.Thread(target=work,daemon=True).start()
        return {'schemaVersion':'city.embedding-control.v1','busy':True,'startupEnabled':False}
