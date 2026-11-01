"""Cross-platform local launcher. One worker per service keeps saga locks local.
Use Docker Compose for Redis/RabbitMQ first. Ctrl+C terminates all children.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1]
os.chdir(root);load_dotenv(root/'.env')
sys.path.insert(0,str(root))
from common.runtime import SERVICES,PORTS
children=[]
try:
    for name in SERVICES+['gateway']:
        port=8000 if name=='gateway' else PORTS[name]
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn',f'services.{name}:app','--host','127.0.0.1','--port',str(port)]))
    print('Gateway: http://localhost:8000/api/docs | API health: http://localhost:8000/health')
    while True:
        for child in children:
            if child.poll() is not None:
                raise RuntimeError('A service stopped. Check its preceding error log.')
        import time
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
