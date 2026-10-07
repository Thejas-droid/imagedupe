"""Desktop display failures must be recoverable without stacked modal dialogs."""
import threading
from types import SimpleNamespace
from unittest.mock import patch
import pytest
pytest.importorskip('PySide6')
from imagedupe.desktop_window import application, AppWindow
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMessageBox, QPushButton


def test_renderer_failure_shows_one_recoverable_panel(tmp_path):
    app=application()
    app.setQuitOnLastWindowClosed(False)
    runtime=SimpleNamespace(url='http://127.0.0.1:12345', token='test', picker=None,
        activation_requested=threading.Event(), app=None, stop=lambda:None)
    window=AppWindow(runtime)
    window.view=QWebEngineView(window)
    window.setCentralWidget(window.view)
    try:
        with patch.object(QMessageBox, 'warning') as warning, patch.object(window, 'show_app') as retry:
            window.renderer_failed(QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus, 9)
            panel=window.centralWidget()
            window.loaded(False)
            assert window.centralWidget() is panel
            warning.assert_not_called()
            panel.findChild(QPushButton).click()
            retry.assert_called_once()
        assert window.probe_result['errors'][0]['exit_code']==9
        assert window.view is None
    finally:
        window.allow_close=True
        window.close()
        window.dispose()
        app.processEvents()
