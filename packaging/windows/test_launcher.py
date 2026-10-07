"""Exercise the real Windows dedicated-window lifecycle and activation."""
import logging
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from imagedupe import desktop
from imagedupe import desktop_window as ui
from PySide6.QtCore import QTimer


def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this check on Windows.')
    observed = {}
    original = ui.AppWindow.show_app
    def show_app(window):
        original(window)
        observed['window'] = window
        def activate():
            other = desktop.DesktopInstance(window.runtime.settings.home)
            try:
                assert not other.acquire()
                assert other.open_existing(timeout=5)
                assert window.runtime.activation_requested.is_set()
                observed['activated'] = True
            finally:
                other.close()
            window.close()
        QTimer.singleShot(1500, activate)
    with tempfile.TemporaryDirectory(prefix='ImageDupe-window-') as directory:
        with patch.dict('os.environ', {'IMAGEDUPE_HOME':str(Path(directory)/'data')}), patch.object(ui.AppWindow, 'show_app', show_app), patch.object(sys, 'argv', ['ImageDupe']):
            assert desktop.main() == 0
        window = observed['window']
        assert observed['activated']
        assert not window.runtime.thread.is_alive()
        assert not (Path(directory)/'data'/'.desktop-session.json').exists()
        # Release rotating log handles before deleting the Windows temp folder.
        for handler in list(logging.getLogger().handlers):
            handler.close();logging.getLogger().removeHandler(handler)
    print('PASS: dedicated window startup, second-instance activation, close and server cleanup.')


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
