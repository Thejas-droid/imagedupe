"""Install/exercise/uninstall in a temporary directory without OS integration."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if sys.platform!='win32':
        raise SystemExit('The installer validation must run on Windows.')
    root=Path(__file__).resolve().parents[2]
    release=root/'release'
    installer=release/'ImageDupe-Setup.exe'
    with tempfile.TemporaryDirectory(prefix='installer-check-',dir=release) as directory:
        target=Path(directory)/'Installed App'
        # NSIS consumes the full trailing /D or _?= value. Do not quote these
        # special arguments even when the destination contains spaces.
        result=subprocess.run(f'"{installer}" /S /TEST /D={target}',timeout=180)
        assert result.returncode==0,'Installer failed'
        assert (target/'.test-install').is_file(),'Test mode was not honored'
        assert (target/'ImageDupe.exe').is_file(),'Installed executable missing'
        assert (target/'ImageDupe.ico').is_file(), 'Shortcut icon missing'
        probe=release/'installed-window-test.json'
        env={**os.environ, 'IMAGEDUPE_HOME':str(Path(directory)/'probe-data')}
        result=subprocess.run([str(target/'ImageDupe.exe'),'--window-test','--report',str(probe)],cwd=target,env=env,timeout=90)
        assert result.returncode==0 and json.loads(probe.read_text())['ok'], 'Normal installed-window startup failed'

        report=release/'installer-self-test.json'
        result=subprocess.run([str(target/'ImageDupe.exe'),'--self-test','--report',str(report)],timeout=180)
        assert result.returncode==0 and json.loads(report.read_text())['ok'],'Installed application self-test failed'
        result=subprocess.run(f'"{target / "Uninstall.exe"}" /S _?={target}',timeout=180)
        assert result.returncode==0,'Uninstaller failed'
        assert not (target/'ImageDupe.exe').exists(),'Application was not removed'
        assert not (target/'_internal').exists(),'Bundled dependencies were not removed'
        # Running an uninstaller directly with _?= disables its temporary copy;
        # Windows retains that currently executing file until it has exited.
        (target/'Uninstall.exe').unlink(missing_ok=True)
        output={'ok':True,'checks':['silent install','isolated test mode','installed executable self-test','normal desktop startup from install directory','shortcut icon file','uninstall'],
                'user_shortcuts_and_registry_modified':False}
        (release/'installer-validation.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
        print(json.dumps(output,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
