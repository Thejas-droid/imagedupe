import io
import numpy as np
from PIL import Image,ImageDraw
from imagedupe.hashing.base import get_spec
from imagedupe.hashing.phash import fingerprint_bytes,encode_hash,parse_hash
from imagedupe.hashing.hamming import hamming_bytes,hamming_many,similarity_pct

def sample():
    im=Image.new('RGB',(64,64),'white');d=ImageDraw.Draw(im);d.rectangle((5,9,40,25),fill='black');d.ellipse((25,28,55,58),fill='gray');b=io.BytesIO();im.save(b,'PNG');return b.getvalue()
def test_phash_is_deterministic_and_versioned():
    data=sample();fp1,_=fingerprint_bytes(data,'phash-v1-256-exif-luma',50_000_000);fp2,_=fingerprint_bytes(data,'phash-v1-256-exif-luma',50_000_000);assert fp1==fp2 and len(fp1)==32;spec=get_spec('phash-v1-256-exif-luma');text=encode_hash(fp1,spec);assert parse_hash(text,spec)==fp1

def test_hamming_oracle():
    a=bytes([0,255]);b=bytes([255,0]);assert hamming_bytes(a,b)==16;v=np.array([[0,255],[255,0],[0,0]],dtype=np.uint8);assert hamming_many(a,v).tolist()==[0,16,8];assert similarity_pct(0,16)==100 and similarity_pct(16,16)==0

def test_golden_phash_vectors_lock_bit_packing_and_algorithm():
    data = sample()
    fp64, _ = fingerprint_bytes(data, 'phash-v1-64-exif-luma', 50_000_000)
    fp256, _ = fingerprint_bytes(data, 'phash-v1-256-exif-luma', 50_000_000)
    assert fp64.hex() == 'a73698c9c8c9136f'
    assert fp256.hex() == 'a7d936c998a6c914c826c826139d2f6bc922ccad33db37d9376bcc94c9269353'


def test_exif_orientation_is_normalized_before_hashing():
    base = Image.new('RGB', (40, 24), 'white')
    draw = ImageDraw.Draw(base)
    draw.rectangle((2, 3, 16, 10), fill='black')
    draw.ellipse((19, 8, 36, 21), fill='gray')
    exif = Image.Exif(); exif[274] = 6
    tagged = io.BytesIO(); base.save(tagged, 'PNG', exif=exif)
    rotated = io.BytesIO(); base.transpose(Image.Transpose.ROTATE_270).save(rotated, 'PNG')
    a, _ = fingerprint_bytes(tagged.getvalue(), 'phash-v1-256-exif-luma', 50_000_000)
    b, _ = fingerprint_bytes(rotated.getvalue(), 'phash-v1-256-exif-luma', 50_000_000)
    assert a == b


def test_transparent_pixels_are_composited_to_fixed_white_background():
    transparent = Image.new('RGBA', (64, 64), (255, 0, 0, 0))
    opaque = Image.new('RGB', (64, 64), 'white')
    a = io.BytesIO(); transparent.save(a, 'PNG')
    b = io.BytesIO(); opaque.save(b, 'PNG')
    fp_a, _ = fingerprint_bytes(a.getvalue(), 'phash-v1-64-exif-luma', 50_000_000)
    fp_b, _ = fingerprint_bytes(b.getvalue(), 'phash-v1-64-exif-luma', 50_000_000)
    assert fp_a == fp_b


def test_hash_parser_rejects_wrong_length_and_spec():
    spec = get_spec('phash-v1-256-exif-luma')
    import pytest
    with pytest.raises(ValueError, match='invalid hash length'):
        parse_hash('abcd', spec)
    with pytest.raises(ValueError, match='fingerprint spec mismatch'):
        parse_hash('phash:64:' + '00' * 8, spec)
