"""Offline desktop lifecycle and native folder selection.

The browser UI talks only to a randomly assigned loopback port. A per-launch
secret authenticates desktop API calls; no external service is required.
"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import secrets
import socket
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FolderPicker:
    """Queue requests from server threads; display dialogs on Qt's main thread."""

    def __init__(self):
        self.requests = queue.Queue()
        self.closed = threading.Event()
        self.lock = threading.Lock()

    def choose(self):
        if self.closed.is_set():
            raise RuntimeError("ImageDupe is closing")
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A folder picker is already open")
        try:
            result = queue.Queue(maxsize=1)
            self.requests.put(result)
            while not self.closed.is_set():
                try:
                    value = result.get(timeout=.2)
                    if isinstance(value, Exception):
                        raise value
                    return value
                except queue.Empty:
                    pass
            raise RuntimeError("ImageDupe is closing")
        finally:
            self.lock.release()

    def pump(self, parent):
        from PySide6.QtWidgets import QFileDialog
        try:
            result = self.requests.get_nowait()
        except queue.Empty:
            return
        try:
            parent.raise_()
            folder = QFileDialog.getExistingDirectory(parent, "Choose your image folder")
            result.put(folder or None)
        except Exception as exc:
            result.put(exc)

    def close(self):
        self.closed.set()


class DesktopInstance:
    """OS-owned lock; a crash releases it without leaving a stale PID lock."""
    def __init__(self, home):
        home.mkdir(parents=True, exist_ok=True)
        self.handle = (home/'.desktop.lock').open('a+b')
        self.state = home/'.desktop-session.json'
        self.owned = False

    def acquire(self):
        self.handle.seek(0,2)
        if not self.handle.tell():
            self.handle.write(b'0');self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.owned = True
        except OSError:
            return False
        return True

    def publish(self, runtime):
        temporary = self.state.with_suffix('.tmp')
        temporary.write_text(json.dumps({'url':runtime.url,'token':runtime.token}),encoding='utf-8')
        if sys.platform != 'win32':temporary.chmod(0o600)
        temporary.replace(self.state)

    def open_existing(self, timeout=45):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                state = json.loads(self.state.read_text(encoding='utf-8'))
                from urllib.parse import urlsplit
                parsed=urlsplit(state['url'])
                if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port:
                    raise ValueError('Invalid desktop session')
                request=Request(state['url']+'/api/v1/desktop/activate',data=b'',headers={'X-ImageDupe-Desktop':state['token']})
                with urlopen(request,timeout=1) as response:
                    if response.status==200:
                        return True
            except (OSError,ValueError,KeyError,URLError):pass
            time.sleep(.15)
        return False

    def close(self):
        if self.owned:
            self.state.unlink(missing_ok=True)
            self.handle.seek(0)
            if sys.platform=='win32':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
            self.owned=False
        self.handle.close()


class DesktopRuntime:
    def __init__(self, settings, picker=None):
        self.settings = settings
        self.token = secrets.token_urlsafe(32)
        self.picker = picker
        self.stop_requested = threading.Event()
        self.activation_requested = threading.Event()
        self.server = None
        self.thread = None
        self.socket = None
        self.app = None
        self.failure = None
        self.url = None

    def start(self, timeout=45):
        if self.stop_requested.is_set():
            raise RuntimeError("ImageDupe startup was cancelled")
        import uvicorn
        from imagedupe.app import create_app
        # Hold the socket until uvicorn takes over, avoiding free-port races.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', 0))
            sock.listen(128)
            self.socket = sock
            self.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
            self.app = create_app(self.settings, desktop=self)
            config = uvicorn.Config(self.app, host='127.0.0.1', port=sock.getsockname()[1],
                                    loop='asyncio', http='h11', ws='none', access_log=False,
                                    log_config=None, timeout_graceful_shutdown=10)
            self.server = uvicorn.Server(config)
            def run():
                try:
                    self.server.run(sockets=[sock])
                except BaseException as exc:
                    self.failure = exc
            self.thread = threading.Thread(target=run, name='imagedupe-server', daemon=True)
            if self.stop_requested.is_set():
                raise RuntimeError('ImageDupe startup was cancelled')
            self.thread.start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.stop_requested.is_set():
                    raise RuntimeError('ImageDupe startup was cancelled')
                if self.failure or not self.thread.is_alive():
                    raise RuntimeError(f"The local server could not start: {self.failure}")
                if self.server.started:
                    request = Request(self.url+'/api/v1/health/ready', headers={'X-ImageDupe-Desktop':self.token})
                    try:
                        with urlopen(request, timeout=1) as response:
                            if response.status == 200:
                                return self.url
                    except (URLError, OSError):
                        pass
                time.sleep(.05)
            raise RuntimeError("ImageDupe took too long to start")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        self.stop_requested.set()
        if self.picker:
            self.picker.close()
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.ident is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=15)
        if self.socket:
            self.socket.close()


def data_home():
    override = os.getenv('IMAGEDUPE_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'win32':
        legacy = Path.home()/'.local'/'share'/'imagedupe'
        if (legacy/'catalog.sqlite3').exists():
            return legacy
        return Path(os.getenv('LOCALAPPDATA', Path.home()/'AppData'/'Local'))/'ImageDupe'/'data'
    return Path.home()/'.local'/'share'/'imagedupe'


def configure_desktop_logging(home):
    logs = home.parent/'logs'
    logs.mkdir(parents=True, exist_ok=True)
    stream = (logs/'launcher.log').open('a', encoding='utf-8', buffering=1)
    # Windowed PyInstaller executables have no stdout/stderr. Libraries that
    # expect file-like streams (including multiprocessing) must still work.
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    handler = RotatingFileHandler(logs/'desktop.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    return logs


def run_self_test(report):
    """Exercise the bundled backend, spawned workers and embedded desktop UI."""
    from PIL import Image, ImageDraw
    from imagedupe.core.config import Settings
    from imagedupe.hashing.base import DEFAULT_SPEC_ID
    from imagedupe.hashing.phash import fingerprint_bytes, encode_hash
    from imagedupe.hashing.base import get_spec
    output = {'ok':False, 'frozen':bool(getattr(sys, 'frozen', False)), 'platform':sys.platform}
    runtime = None
    try:
        with tempfile.TemporaryDirectory(prefix='ImageDupe-check-') as directory:
            base = Path(directory)
            root = base/'Pictures with spaces';root.mkdir()
            image = Image.new('RGB', (96, 72), 'white')
            ImageDraw.Draw(image).rectangle((12, 8, 63, 52), fill='teal')
            image.save(root/'sample.png');image.save(root/'duplicate.png')
            runtime = DesktopRuntime(Settings(home=base/'data', worker_count=2), FolderPicker())
            runtime.start()
            def api(path, data=None):
                request = Request(runtime.url+path, data=json.dumps(data).encode() if data is not None else None,
                                  headers={'X-ImageDupe-Desktop':runtime.token,'Content-Type':'application/json'})
                with urlopen(request, timeout=30) as response:
                    return json.load(response)
            with urlopen(runtime.url+'/', timeout=10) as response:
                assert b'id="matchType"' in response.read(), 'UI missing from package'
            with urlopen(runtime.url+'/assets/app.js', timeout=10) as response:
                assert b'matchingThreshold' in response.read(), 'JavaScript missing from package'
            try:
                urlopen(runtime.url+'/api/v1/collections', timeout=5)
                raise AssertionError('Desktop API must require a session')
            except HTTPError as exc:
                assert exc.code == 401
            collection = api('/api/v1/collections', {'name':'Self-test', 'roots':[{'path':str(root)}]})
            cid = collection['id']
            def wait_job(job):
                deadline = time.monotonic()+90
                while time.monotonic()<deadline:
                    result=api('/api/v1/jobs/'+job['job_id'])
                    if result['state']=='SUCCEEDED':return result
                    if result['state'] in {'FAILED','CANCELLED','ABORTED'}:raise RuntimeError(str(result))
                    time.sleep(.15)
                raise RuntimeError('Bundled worker test timed out')
            wait_job(api(f'/api/v1/collections/{cid}/scan', {}))
            counts=api(f'/api/v1/collections/{cid}')['counts']
            assert counts['valid']==2 and counts['failed']==0, counts
            wait_job(api(f'/api/v1/collections/{cid}/rebuild', {'backend':'auto','config':{}}))
            fp,_=fingerprint_bytes((root/'sample.png').read_bytes(), DEFAULT_SPEC_ID,50_000_000)
            results=api('/api/v1/search/hash',{'collection_id':cid,'hash':encode_hash(fp,get_spec(DEFAULT_SPEC_ID)),'k':100,'max_hamming':102})
            assert len(results['results'])==2,results
            thumb=results['results'][0]['thumbnail_url']
            with urlopen(Request(runtime.url+thumb, headers={'X-ImageDupe-Desktop':runtime.token}),timeout=10) as response:
                assert response.read().startswith(b'\xff\xd8'), 'Thumbnail must be JPEG'
            from imagedupe.desktop_window import renderer_self_test
            renderer_self_test(runtime)
            output.update(ok=True, searchable_images=counts['valid'], matches=len(results['results']),
                          checks=['bundled HTML/JS','session protection','collection API','spawned workers','index build','search','thumbnail','Qt embedded UI','native folder dialog','download dialog','window icon'])
            runtime.stop();runtime=None
    except BaseException as exc:
        output['error']=str(exc)
        logging.exception('desktop_self_test_failed')
    finally:
        if runtime:runtime.stop()
        if report:
            Path(report).parent.mkdir(parents=True, exist_ok=True)
            Path(report).write_text(json.dumps(output,indent=2),encoding='utf-8')
    return 0 if output['ok'] else 1


def main():
    parser=argparse.ArgumentParser(description='ImageDupe offline desktop application')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--window-test', action='store_true', help='Probe the normal desktop startup and close automatically')
    parser.add_argument('--report', help='Write self-test results to a JSON file')
    args=parser.parse_args()
    if args.window_test and not args.report:
        parser.error('--window-test requires --report')
    if args.self_test:
        return run_self_test(args.report)
    from imagedupe.desktop_window import run_window
    return run_window(args.report if args.window_test else None)
