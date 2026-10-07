from pathlib import Path
from imagedupe.hashing.base import get_spec
from imagedupe.hashing.phash import encode_hash
from conftest import make_image

def build(env):
    s,c,i,cs,ss,root=env;make_image(root/'a.png',1);make_image(root/'b.png',2);make_image(root/'c.png',3);coll=cs.create('demo',[{'path':str(root),'recursive':True}],'phash-v1-256-exif-luma','exact');stats=cs.scan(coll['id']);assert stats['hashed']==3;m=i.build(coll['id'],'numpy-exact');return coll['id'],root,m

def test_create_scan_build_search_and_hash_parity(env):
    s,c,i,cs,ss,root=env;cid,root,m=build(env);data=(root/'a.png').read_bytes();by_image=ss.image(cid,data,'a.png',20,'auto');assert by_image['results'][0]['classification']=='BYTE_EXACT';assert by_image['results'][0]['hamming_distance']==0;text=by_image['query']['hash_hex'];by_hash=ss.hash(cid,text,20,'auto');assert [x['image_id'] for x in by_hash['results']]==[x['image_id'] for x in by_image['results']];assert by_hash['results'][0]['classification']=='PERCEPTUAL_HASH_EXACT'

def test_incremental_cache_and_moved_content_reuse(env):
    s,c,i,cs,ss,root=env;cid,root,m=build(env);second=cs.scan(cid);assert second['cached']==3 and second['hashed']==0;(root/'b.png').rename(root/'moved.png');third=cs.scan(cid);assert third['content_reused']==1 and third['hashed']==0

def test_same_visual_hash_different_bytes_not_byte_exact(env):
    s,c,i,cs,ss,root=env;original=make_image(root/'same.png',8,metadata=False);coll=cs.create('demo',[{'path':str(root)}],'phash-v1-256-exif-luma','exact');cs.scan(coll['id']);i.build(coll['id'],'numpy-exact');query=root/'query.png';make_image(query,8,metadata=True);r=ss.image(coll['id'],query.read_bytes(),'query.png',10);hit=next(x for x in r['results'] if x['filename']=='same.png');assert hit['hamming_distance']==0;assert hit['classification']=='PERCEPTUAL_HASH_EXACT'

def test_failed_rebuild_keeps_previous_generation(env):
    s,c,i,cs,ss,root=env;cid,root,m=build(env);active=c.active_generation(cid);assert active['generation']==m['generation']
    try:i.build(cid,'ngt-hamming')
    except RuntimeError:pass
    assert c.active_generation(cid)['generation']==active['generation'];assert ss.image(cid,(root/'a.png').read_bytes(),'a.png',10)['results']
