import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from imagedupe.app import create_app
from imagedupe.core.config import Settings
from imagedupe.desktop import DesktopInstance, FolderPicker, data_home


@pytest.fixture
def desktop_client(tmp_path):
    picker = SimpleNamespace(choose=lambda: str(tmp_path/'Photos'))
    desktop = SimpleNamespace(url='http://127.0.0.1:8765', token='private-desktop-secret', picker=picker, activation_requested=threading.Event())
    with TestClient(create_app(Settings(home=tmp_path/'home',worker_count=1), desktop=desktop),base_url=desktop.url) as client:
        yield client,desktop


def test_desktop_requires_session_and_rejects_other_origins(desktop_client):
    client,desktop=desktop_client
    assert client.get('/api/v1/collections').status_code==401
    headers={'X-ImageDupe-Desktop':desktop.token}
    assert client.get('/api/v1/collections',headers=headers).status_code==200
    assert client.post('/api/v1/desktop/folder',headers={**headers,'Origin':'https://outside.example'}).status_code==403
    assert client.get('/',headers={'Host':'outside.example'}).status_code==403
    assert client.get('/assets/app.js').status_code==200


def test_desktop_session_cookie_and_native_folder_selection(desktop_client):
    client,desktop=desktop_client
    assert client.post('/api/v1/desktop/session',headers={'X-ImageDupe-Desktop':desktop.token}).status_code==200
    assert client.cookies.get('imagedupe_desktop')==desktop.token
    response=client.get('/api/v1/desktop')
    assert response.json()=={'enabled':True,'folder_picker':True}
    assert client.post('/api/v1/desktop/folder').json()['path'].endswith('Photos')
    desktop.picker.choose=lambda:None
    assert client.post('/api/v1/desktop/folder').json()=={'path':None}


def test_cli_does_not_offer_a_native_picker(tmp_path):
    with TestClient(create_app(Settings(home=tmp_path/'home',worker_count=1))) as client:
        assert client.get('/api/v1/desktop').json()=={'enabled':False,'folder_picker':False}
        assert client.post('/api/v1/desktop/folder').status_code==404


def test_picker_shutdown_unblocks_pending_request():
    picker=FolderPicker();result=[]
    def choose():
        try:picker.choose()
        except RuntimeError as exc:result.append(str(exc))
    thread=threading.Thread(target=choose);thread.start()
    pending=picker.requests.get(timeout=2)
    with pytest.raises(RuntimeError,match='already open'):picker.choose()
    picker.close();thread.join(timeout=2)
    assert not thread.is_alive() and result==['ImageDupe is closing']


def test_instance_lock_and_state_are_released(tmp_path):
    first=DesktopInstance(tmp_path);second=DesktopInstance(tmp_path)
    try:
        assert first.acquire()
        assert not second.acquire()
        first.publish(SimpleNamespace(url='http://127.0.0.1:1234',token='token'))
        assert json.loads(first.state.read_text())['token']=='token'
        first.close()
        assert not first.state.exists()
        assert second.acquire()
    finally:
        if not first.handle.closed:first.close()
        second.close()


def test_data_home_honors_explicit_location(tmp_path,monkeypatch):
    monkeypatch.setenv('IMAGEDUPE_HOME',str(tmp_path/'separate-data'))
    assert data_home()==(tmp_path/'separate-data').resolve()


def test_cancelled_runtime_does_not_start_a_server(tmp_path):
    from imagedupe.desktop import DesktopRuntime
    runtime=DesktopRuntime(Settings(home=tmp_path/'home',worker_count=1))
    runtime.stop()
    with pytest.raises(RuntimeError,match='cancelled'):runtime.start()
    assert runtime.server is None


def test_second_instance_activation_requires_authentication(desktop_client):
    client, desktop = desktop_client
    assert client.post('/api/v1/desktop/activate').status_code == 401
    assert not desktop.activation_requested.is_set()
    response = client.post('/api/v1/desktop/activate', headers={'X-ImageDupe-Desktop': desktop.token})
    assert response.json() == {'activated': True}
    assert desktop.activation_requested.is_set()
