from __future__ import annotations

import threading
from pathlib import Path

import pytest

from conftest import make_image
from imagedupe.indexes.backends import NumpyExact
from imagedupe.indexes.manager import IndexManager
from imagedupe.core.search import SearchService


def prepare(env):
    settings, catalog, indexes, collections, search, root = env
    make_image(root / 'a.png', 1)
    make_image(root / 'b.png', 2)
    collection = collections.create(
        'reliability', [{'path': str(root)}], 'phash-v1-256-exif-luma', 'exact'
    )
    collections.scan(collection['id'])
    first = indexes.build(collection['id'], 'numpy-exact')
    return collection['id'], first


def test_active_generation_remains_searchable_during_rebuild(env, monkeypatch):
    settings, catalog, indexes, collections, search, root = env
    cid, first = prepare(env)
    before = search.image(cid, (root/'a.png').read_bytes(), 'a.png', 10)
    assert before['search']['generation'] == first['generation']

    started = threading.Event(); release = threading.Event(); original_save = NumpyExact.save
    def slow_save(self, path):
        original_save(self, path)
        started.set()
        assert release.wait(10)
    monkeypatch.setattr(NumpyExact, 'save', slow_save)
    errors=[]
    def rebuild():
        try: indexes.build(cid, 'numpy-exact')
        except Exception as exc: errors.append(exc)
    thread=threading.Thread(target=rebuild, daemon=True);thread.start()
    assert started.wait(10)
    during=search.image(cid, (root/'a.png').read_bytes(), 'a.png', 10)
    assert during['search']['generation'] == first['generation']
    release.set();thread.join(10)
    assert not errors
    after=search.image(cid, (root/'a.png').read_bytes(), 'a.png', 10)
    assert after['search']['generation'] == first['generation'] + 1


def test_cancelled_build_never_promotes(env):
    settings, catalog, indexes, collections, search, root = env
    cid, first = prepare(env)
    with pytest.raises(RuntimeError, match='JOB_CANCELLED'):
        indexes.build(cid, 'numpy-exact', cancel_check=lambda: True)
    assert catalog.active_generation(cid)['generation'] == first['generation']
    assert not list((settings.index_dir/cid).glob('.*.tmp'))


def test_restart_loads_persisted_active_generation(env):
    settings, catalog, indexes, collections, search, root = env
    cid, first = prepare(env)
    fresh=IndexManager(catalog, settings.index_dir, settings)
    fresh_search=SearchService(catalog, fresh, settings)
    response=fresh_search.image(cid, (root/'a.png').read_bytes(), 'a.png', 10)
    assert response['search']['generation'] == first['generation']
    fresh.close()


def test_file_update_and_delete_are_reflected_by_delta_and_tombstones(env):
    settings, catalog, indexes, collections, search, root = env
    cid, first = prepare(env)
    make_image(root/'a.png', 77)
    (root/'b.png').unlink()
    scan=collections.scan(cid)
    assert scan['hashed'] == 1
    assert scan['missing'] == 1
    state=indexes.delta_status(cid)
    assert state['delta_bucket_count'] >= 1
    assert state['tombstone_count'] >= 1
    result=search.image(cid,(root/'a.png').read_bytes(),'a.png',10)
    assert result['results'][0]['filename']=='a.png'
    assert all(item['filename']!='b.png' for item in result['results'])


def test_max_hamming_classifies_nonzero_matches_as_near_duplicates(env):
    settings, catalog, indexes, collections, search, root = env
    cid, first = prepare(env)
    response=search.image(cid,(root/'a.png').read_bytes(),'a.png',10,'auto',256)
    b=next(item for item in response['results'] if item['filename']=='b.png')
    assert b['hamming_distance'] > 0
    assert b['classification']=='NEAR_DUPLICATE'
