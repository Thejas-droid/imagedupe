"""Validate normal frozen GUI startup from the same folder as a shortcut."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
root=Path(__file__).resolve().parents[2]
if sys.platform!='win32':raise SystemExit('Run on Windows')
with tempfile.TemporaryDirectory(prefix='ImageDupe-startup-') as directory:
    env={**os.environ, 'IMAGEDUPE_HOME':str(Path(directory)/'data')}
    report=root/'release/window-test.json'
    exe=root/'dist/ImageDupe/ImageDupe.exe'
    result=subprocess.run([str(exe),'--window-test','--report',str(report)],cwd=exe.parent,env=env,timeout=90)
    output=json.loads(report.read_text())
    assert result.returncode==0 and output['ok'] and not output['errors'], output
    print(json.dumps(output,indent=2))
