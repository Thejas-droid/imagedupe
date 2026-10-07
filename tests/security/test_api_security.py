import io
from fastapi.testclient import TestClient
from PIL import Image
from imagedupe.app import create_app
from imagedupe.core.config import Settings

def test_invalid_image_and_upload_limit(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1,max_upload_bytes=32);client=TestClient(create_app(s));root=tmp_path/'images';root.mkdir();r=client.post('/api/v1/collections',json={'name':'x','roots':[{'path':str(root)}]});cid=r.json()['id'];bad=client.post('/api/v1/search/image',files={'image':('x.jpg',b'not image','image/jpeg')},data={'collection_id':cid});assert bad.status_code in (413,422)

def test_decoded_pixel_limit(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1,max_upload_bytes=100000,max_decoded_pixels=100);client=TestClient(create_app(s));root=tmp_path/'images';root.mkdir();cid=client.post('/api/v1/collections',json={'name':'x','roots':[{'path':str(root)}]}).json()['id'];b=io.BytesIO();Image.new('RGB',(20,20)).save(b,'PNG');r=client.post('/api/v1/search/image',files={'image':('x.png',b.getvalue(),'image/png')},data={'collection_id':cid});assert r.status_code==422;assert r.json()['code']=='IMAGE_TOO_LARGE'

def test_fake_extension_mime_and_traversal_are_rejected(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1,max_upload_bytes=100000)
    with TestClient(create_app(s)) as client:
        root=tmp_path/'images';root.mkdir();cid=client.post('/api/v1/collections',json={'name':'x','roots':[{'path':str(root)}]}).json()['id']
        b=io.BytesIO();Image.new('RGB',(10,10),'white').save(b,'PNG');payload=b.getvalue()
        fake=client.post('/api/v1/search/image',files={'image':('x.txt',payload,'image/png')},data={'collection_id':cid})
        assert fake.status_code==415 and fake.json()['code']=='UNSUPPORTED_IMAGE_FORMAT'
        mime=client.post('/api/v1/search/image',files={'image':('x.png',payload,'text/plain')},data={'collection_id':cid})
        assert mime.status_code==415 and mime.json()['code']=='UNSUPPORTED_IMAGE_FORMAT'
        traversal=client.post('/api/v1/search/image',files={'image':('../x.png',payload,'image/png')},data={'collection_id':cid})
        # Multipart parsers may normalize the filename; the service-level traversal test below is authoritative.
        assert traversal.status_code in (415,503)
        service=client.app.state.search
        import pytest
        with pytest.raises(Exception) as exc:
            service.image(cid,payload,'../x.png',content_type='image/png')
        assert 'UNSUPPORTED_IMAGE_FORMAT' in str(exc.value)


def test_untrusted_decompression_bomb_warning_is_an_error(tmp_path, monkeypatch):
    import PIL.Image as PILImage
    from imagedupe.hashing.phash import fingerprint_bytes
    b=io.BytesIO();Image.new('RGB',(20,20),'white').save(b,'PNG')
    monkeypatch.setattr(PILImage,'MAX_IMAGE_PIXELS',300)
    import pytest
    with pytest.raises(Exception) as exc:
        fingerprint_bytes(b.getvalue(),'phash-v1-64-exif-luma',10_000,True)
    assert 'IMAGE_TOO_LARGE' in str(exc.value)


def test_rate_limit_returns_problem_details(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1,request_rate_per_minute=2)
    with TestClient(create_app(s)) as client:
        assert client.get('/api/v1/health/live').status_code==200
        assert client.get('/api/v1/health/live').status_code==200
        limited=client.get('/api/v1/health/live')
        assert limited.status_code==429
        assert limited.headers['content-type'].startswith('application/problem+json')
        assert limited.json()['code']=='RATE_LIMITED'
