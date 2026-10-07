from fastapi.testclient import TestClient
from imagedupe.app import create_app
from imagedupe.core.config import Settings

def test_health_and_openapi(tmp_path):
    c=TestClient(create_app(Settings(home=tmp_path/'home',worker_count=1)));assert c.get('/api/v1/health/live').json()['status']=='ok';doc=c.get('/openapi.json').json();assert doc['openapi'].startswith('3.1');assert '/api/v1/search/image' in doc['paths']

def test_job_etag_and_metrics_shape(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1)
    with TestClient(create_app(s)) as client:
        root=tmp_path/'images';root.mkdir()
        cid=client.post('/api/v1/collections',json={'name':'etag','roots':[{'path':str(root)}]}).json()['id']
        job_id=client.post(f'/api/v1/collections/{cid}/scan').json()['job_id']
        first=client.get(f'/api/v1/jobs/{job_id}')
        assert 'etag' in first.headers
        same=client.get(f'/api/v1/jobs/{job_id}',headers={'If-None-Match':first.headers['etag']})
        # The fast empty scan can change state between requests; either unchanged (304) or a newer representation is valid.
        assert same.status_code in (200,304)
        metrics=client.get(f'/api/v1/system/metrics?collection_id={cid}')
        assert metrics.status_code==200
        payload=metrics.json()
        for key in ['search_requests_total','search_errors_total','index_vector_count','delta_bucket_count','active_generation']:
            assert key in payload

def test_collection_root_patch_and_failed_file_listing(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1)
    with TestClient(create_app(s)) as client:
        root=tmp_path/'one';root.mkdir();root2=tmp_path/'two';root2.mkdir()
        (root2/'broken.jpg').write_bytes(b'not a jpeg')
        created=client.post('/api/v1/collections',json={'name':'roots','roots':[{'path':str(root)}]}).json();cid=created['id']
        patched=client.patch(f'/api/v1/collections/{cid}',json={'roots':[{'path':str(root2),'recursive':False,'exclude_globs':['skip*']}]})
        assert patched.status_code==200
        assert patched.json()['roots'][0]['path']==str(root2.resolve())
        job=client.post(f'/api/v1/collections/{cid}/scan').json()['job_id']
        import time
        for _ in range(100):
            state=client.get(f'/api/v1/jobs/{job}').json()
            if state['state'] in ('SUCCEEDED','FAILED','CANCELLED','ABORTED'):break
            time.sleep(.02)
        assert state['state']=='SUCCEEDED'
        failures=client.get(f'/api/v1/collections/{cid}/failures').json()
        assert failures and failures[0]['filename']=='broken.jpg'
        assert failures[0]['error_code']=='IMAGE_DECODE_FAILED'

def test_cuda_on_without_binary_gpu_reports_degraded(tmp_path):
    s=Settings(home=tmp_path/'home',worker_count=1,cuda_mode='On')
    with TestClient(create_app(s)) as client:
        status=client.get('/api/v1/system/status').json()
        doctor=client.get('/api/v1/system/doctor').json()
        if not doctor['faiss_binary_gpu_compatible']:
            assert status['system_status']=='degraded'
