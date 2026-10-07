"""Dedicated offline desktop window; Qt remains optional for CLI users."""
from pathlib import Path
import logging
import os
import queue
import sys
import threading
import time
# Select graphics mode before importing Qt or creating the Chromium process.
# This interface displays static photos; software rendering avoids driver issues.
if sys.platform == 'win32' and os.getenv('IMAGEDUPE_RENDER_MODE', 'software') == 'software':
    flags = os.getenv('QTWEBENGINE_CHROMIUM_FLAGS', '')
    if '--disable-gpu' not in flags.split():
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (flags+' --disable-gpu').strip()
    os.environ.setdefault('QSG_RHI_PREFER_SOFTWARE_RENDERER', '1')

from PySide6.QtCore import QTimer, QUrl, Qt, QCoreApplication, QEvent, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QMessageBox, QFileDialog, QWidget, QVBoxLayout, QPushButton
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

ICON = Path(__file__).parent/'assets'/'imagedupe.ico'


def application():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ImageDupe.Desktop')
    def qt_log(kind, context, message):
        logging.getLogger('imagedupe.qt').warning('%s', message)
    qInstallMessageHandler(qt_log)
    app = QApplication.instance() or QApplication(['ImageDupe'])
    app.setApplicationName('ImageDupe')
    app.setWindowIcon(QIcon(str(ICON)))
    return app


class LocalPage(QWebEnginePage):
    def __init__(self, profile, parent, origin):
        super().__init__(profile, parent)
        self.origin = QUrl(origin)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return (url.scheme() == 'http' and url.host() == self.origin.host()
                and url.port() == self.origin.port()) or url.toString() == 'about:blank'

    def createWindow(self, window_type):
        return None


class AppWindow(QMainWindow):
    def __init__(self, runtime, instance=None, logs=None, probe_report=None):
        super().__init__()
        self.runtime, self.instance, self.logs = runtime, instance, logs
        self.events = queue.Queue()
        self.probe_report = probe_report
        self.probe_ready_since = None
        self.probe_result = {'ok': False, 'checks': [], 'errors': []}
        self.display_error = False
        self.probe_started = time.monotonic()
        self.closing = False
        self.allow_close = False
        self.setWindowTitle('ImageDupe')
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1280, 850)
        self.setMinimumSize(850, 600)
        self.status = QLabel('Starting your offline image finder…')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet('background:#f5f7f8;color:#135b57;font:20px "Segoe UI";')
        self.setCentralWidget(self.status)
        self.profile = QWebEngineProfile(self)
        self.profile.downloadRequested.connect(self.save_download)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def start(self):
        def worker():
            try:
                self.runtime.start()
                if self.instance:
                    self.instance.publish(self.runtime)
                self.events.put(('ready', None))
            except BaseException as exc:
                logging.exception('desktop_start_failed')
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, name='imagedupe-start', daemon=True).start()

    def show_app(self):
        self.display_error = False
        self.view = QWebEngineView(self)
        self.view.setPage(LocalPage(self.profile, self.view, self.runtime.url))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.loadFinished.connect(self.loaded)
        self.view.page().renderProcessTerminated.connect(self.renderer_failed)
        self.setCentralWidget(self.view)
        self.view.load(QUrl(self.runtime.url+'/#desktop='+self.runtime.token))

    def loaded(self, ok):
        if not ok and not self.closing:
            self.display_failed('The interface could not load.')

    def renderer_failed(self, status, code):
        logging.error('desktop_renderer_terminated status=%s exit_code=%s', status.name, code)
        self.probe_result['errors'].append({'status': status.name, 'exit_code': code})
        if not self.closing:
            self.display_failed('The display process stopped unexpectedly.')

    def display_failed(self, reason):
        if self.display_error:
            return
        self.display_error = True
        logging.error('desktop_display_failed: %s', reason)
        self.probe_result['errors'].append(reason)
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.addStretch()
        label = QLabel('ImageDupe could not display the interface.\n'+reason+'\nYour saved collections are preserved.', panel)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        retry = QPushButton('Try again', panel)
        retry.clicked.connect(self.show_app)
        layout.addWidget(retry, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        # Keep the page alive while its error signals finish, avoiding recursion.
        old_view = self.takeCentralWidget()
        old_view.hide()
        old_view.deleteLater()
        self.view = None
        self.setCentralWidget(panel)

    def check_probe(self):
        if not self.probe_report or self.closing:
            return
        if self.display_error or time.monotonic()-self.probe_started > 45:
            self.probe_result['errors'].append('Startup probe failed or timed out')
            self.close()
            return
        if getattr(self, 'view', None) is None:
            return
        def ready(value):
            if not value or self.closing:
                return
            if self.probe_ready_since is None:
                self.probe_ready_since = time.monotonic()
            if time.monotonic()-self.probe_ready_since >= 2:
                self.probe_result.update(ok=True, checks=['normal desktop startup', 'authenticated embedded UI', 'stable renderer', 'window icon'])
                self.close()
        self.view.page().runJavaScript("Boolean(document.querySelector('#browseFolder') && !document.querySelector('#browseFolder').hidden && document.querySelector('#desktopNote') && !document.querySelector('#desktopNote').hidden)", ready)

    def save_download(self, download):
        path, _ = QFileDialog.getSaveFileName(self, 'Save ImageDupe export', download.downloadFileName())
        if not path:
            download.cancel()
            return
        destination = Path(path)
        download.setDownloadDirectory(str(destination.parent))
        download.setDownloadFileName(destination.name)
        download.accept()

    def tick(self):
        self.check_probe()
        if not self.closing and self.runtime.picker:
            self.runtime.picker.pump(self)
        if self.runtime.activation_requested.is_set():
            self.runtime.activation_requested.clear()
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        try:
            kind, value = self.events.get_nowait()
        except queue.Empty:
            return
        if kind == 'ready' and not self.closing:
            self.show_app()
        elif kind == 'error' and not self.closing:
            QMessageBox.critical(self, 'ImageDupe could not start', f'{value}\n\nDetails: {self.logs}')
            self.close()
        elif kind == 'closed':
            self.allow_close = True
            self.close()

    def closeEvent(self, event):
        if self.allow_close:
            self.timer.stop()
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        catalog = self.runtime.app.state.catalog if self.runtime.app else None
        jobs = [catalog.active_job_for_collection(c['id']) for c in catalog.list_collections()] if catalog else []
        jobs = [job for job in jobs if job]
        if jobs and QMessageBox.question(self, 'Close ImageDupe?', 'An image scan or index preparation is running. Closing will cancel it. You can scan again next time.') != QMessageBox.StandardButton.Yes:
            return
        self.closing = True
        if getattr(self, 'view', None) is not None:
            self.view.setEnabled(False)
        self.setWindowTitle('ImageDupe — closing…')
        for job in jobs:
            catalog.request_cancel(job['id'])
        def stop():
            self.runtime.stop()
            self.events.put(('closed', None))
        threading.Thread(target=stop, name='imagedupe-stop', daemon=True).start()

    def dispose(self):
        # Drain page/view deletion before deleting their profile. processEvents()
        # alone does not flush DeferredDelete after the main event loop exits.
        self.timer.stop()
        if getattr(self, 'view', None) is not None:
            view = self.takeCentralWidget()
            view.page().deleteLater()
            view.deleteLater()
            self.view = None
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.profile.deleteLater()
        self.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def run_window(probe_report=None):
    from imagedupe.desktop import data_home, configure_desktop_logging, DesktopInstance, DesktopRuntime, FolderPicker
    from imagedupe.core.config import Settings
    home = data_home()
    logs = configure_desktop_logging(home)
    app = application()
    instance = DesktopInstance(home)
    if not instance.acquire():
        try:
            if not instance.open_existing():
                QMessageBox.warning(None, 'ImageDupe is already running', 'Wait for the existing ImageDupe window to finish starting or closing, then try again.')
            return 0
        finally:
            instance.close()
    runtime = DesktopRuntime(Settings(home=home, worker_count=int(os.getenv('IMAGEDUPE_WORKERS', str(max(1, min(4, (os.cpu_count() or 2)-2)))))), FolderPicker())
    window = AppWindow(runtime, instance, logs, probe_report)
    window.show()
    window.start()
    try:
        result = app.exec()
        if probe_report:
            import json
            report = Path(probe_report)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(window.probe_result, indent=2), encoding='utf-8')
            return 0 if window.probe_result['ok'] else 1
        return result
    finally:
        runtime.stop()
        instance.close()
        window.dispose()


def renderer_self_test(runtime):
    """Render the real authenticated UI using the bundled Chromium process."""
    from unittest.mock import patch
    from imagedupe.desktop import FolderPicker
    app = application()
    app.setQuitOnLastWindowClosed(False)
    window = AppWindow(runtime)
    window.show_app()
    window.show()
    ready = []
    deadline = time.monotonic()+45
    while time.monotonic() < deadline:
        app.processEvents()
        if not ready:
            window.view.page().runJavaScript("Boolean(document.querySelector('#matchType') && document.querySelector('#browseFolder') && !document.querySelector('#browseFolder').hidden && document.querySelector('#collectionCards article'))", lambda value: ready.append(value) if value else None)
        if ready:
            break
        time.sleep(.05)
    assert ready, 'Embedded UI did not authenticate and render collections'
    assert not window.windowIcon().isNull(), 'Window icon missing'
    assert not window.view.page().acceptNavigationRequest(QUrl('https://example.com'), QWebEnginePage.NavigationType.NavigationTypeLinkClicked, True)
    picker = FolderPicker()
    chosen = []
    worker = threading.Thread(target=lambda: chosen.append(picker.choose()))
    worker.start()
    with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(runtime.settings.home)):
        deadline = time.monotonic()+5
        while worker.is_alive() and time.monotonic()<deadline:
            picker.pump(window)
            app.processEvents()
            time.sleep(.05)
    worker.join(1)
    assert chosen == [str(runtime.settings.home)], 'Native picker bridge failed'
    exports = []
    window.profile.downloadRequested.disconnect(window.save_download)
    def export(download):
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(runtime.settings.home/'export.csv'), '')):
            window.save_download(download)
        download.isFinishedChanged.connect(lambda: exports.append(download.state()))
    window.profile.downloadRequested.connect(export)
    window.view.page().runJavaScript("(()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['test-export'],{type:'text/csv'}));a.download='export.csv';a.click()})()")
    deadline=time.monotonic()+10
    while not exports and time.monotonic()<deadline:
        app.processEvents();time.sleep(.05)
    assert (runtime.settings.home/'export.csv').read_text() == 'test-export', 'Native export save failed'
    window.allow_close=True
    window.close()
    window.dispose()
    app.setQuitOnLastWindowClosed(True)
