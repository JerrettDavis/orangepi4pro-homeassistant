#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import time
while True:
    try:
        data = json.loads(Path('/run/opiha/status/vision.json').read_text())
        age = time.time() - float(data['timestamp'])
        if data.get('available') and data.get('person') and 0 <= age < 15:
            subprocess.run(['xset', 'dpms', 'force', 'on'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError, KeyError):
        pass
    time.sleep(5)
