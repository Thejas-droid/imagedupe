# Build on Windows using Python 3.12 x64. Includes the offline backend and UI.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(root/'packaging/windows'))
from collect_licenses import license_data
a = Analysis(
    [str(root / 'scripts' / 'windows_entry.py')],
    pathex=[str(root / 'src')],
    datas=[(str(root/'src/imagedupe/web'),'imagedupe/web'), (str(root/'src/imagedupe/assets'),'imagedupe/assets')] + license_data() + [(str(root/'LICENSE'),'.'), (str(root/'packaging/windows/qt-notices'),'licenses/Qt')],
    hiddenimports=['uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl',
                   'uvicorn.lifespan.on','PIL.JpegImagePlugin','PIL.PngImagePlugin','PIL.WebPImagePlugin'],
    excludes=['pytest','httpx','faiss','ngt','matplotlib','IPython','uvloop','tkinter','PyQt5','PyQt6','PySide2'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ImageDupe',
          console=False, debug=False, strip=False, upx=False,
          icon=str(root/'src/imagedupe/assets/imagedupe.ico'),
          version=str(root/'packaging/windows/version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ImageDupe')
