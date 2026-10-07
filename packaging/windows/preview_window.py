"""Capture the dedicated desktop window with a temporary empty catalog."""
from pathlib import Path
import tempfile
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from imagedupe.desktop import DesktopRuntime, FolderPicker
from imagedupe.core.config import Settings
from imagedupe.desktop_window import application, AppWindow

def main():
    with tempfile.TemporaryDirectory(prefix='ImageDupe-preview-') as directory:
        runtime=DesktopRuntime(Settings(home=Path(directory)/'data',worker_count=1),FolderPicker())
        runtime.start()
        app=application();app.setQuitOnLastWindowClosed(False)
        window=AppWindow(runtime);window.show_app();window.show()
        ready=[]
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            app.processEvents()
            window.view.page().runJavaScript("Boolean(document.querySelector('#browseFolder') && !document.querySelector('#browseFolder').hidden)",lambda value: ready.append(value) if value else None)
            if ready:break
            time.sleep(.1)
        assert ready
        for _ in range(10):app.processEvents();time.sleep(.1)
        window.grab().save('release/desktop-preview.png')
        window.allow_close=True;window.close();window.dispose();runtime.stop()

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
