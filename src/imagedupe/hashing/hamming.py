import numpy as np
_POP=np.array([i.bit_count() for i in range(256)],dtype=np.uint8)
def hamming_bytes(a,b):
    aa=np.frombuffer(a,dtype=np.uint8) if isinstance(a,(bytes,bytearray)) else np.asarray(a,dtype=np.uint8)
    bb=np.frombuffer(b,dtype=np.uint8) if isinstance(b,(bytes,bytearray)) else np.asarray(b,dtype=np.uint8)
    if aa.shape!=bb.shape: raise ValueError("fingerprints must have same length")
    return int(_POP[np.bitwise_xor(aa,bb)].sum())
def hamming_many(q,vectors):
    q=np.frombuffer(q,dtype=np.uint8) if isinstance(q,(bytes,bytearray)) else np.asarray(q,dtype=np.uint8)
    v=np.asarray(vectors,dtype=np.uint8)
    if v.ndim!=2 or v.shape[1]!=q.size: raise ValueError("query/vector dimensions do not match")
    return _POP[np.bitwise_xor(v,q)].sum(axis=1,dtype=np.uint16)
def similarity_pct(distance,bits): return max(0.0,min(100.0,100*(1-distance/bits)))
