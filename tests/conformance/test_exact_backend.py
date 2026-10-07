import numpy as np
from imagedupe.indexes.backends import NumpyExact
from imagedupe.hashing.hamming import hamming_many

def test_exact_matches_independent_oracle():
    rng=np.random.default_rng(42);v=rng.integers(0,256,size=(200,32),dtype=np.uint8);ids=np.arange(1000,1200,dtype=np.int64);q=v[17].copy();b=NumpyExact(256);b.build(v,ids,{});got,d=b.search(q,20);oracle=hamming_many(q,v);order=np.lexsort((ids,oracle))[:20];assert got.tolist()==ids[order].tolist();assert d.tolist()==oracle[order].tolist()
