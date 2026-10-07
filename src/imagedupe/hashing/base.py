from dataclasses import dataclass
@dataclass(frozen=True,slots=True)
class FingerprintSpec:
    spec_id:str; algorithm:str; bits:int; hash_size:int; highfreq_factor:int=4; alpha_background:tuple[int,int,int]=(255,255,255)
    @property
    def byte_length(self): return self.bits//8
SPECS={
 "phash-v1-64-exif-luma":FingerprintSpec("phash-v1-64-exif-luma","phash",64,8),
 "phash-v1-256-exif-luma":FingerprintSpec("phash-v1-256-exif-luma","phash",256,16),
}
DEFAULT_SPEC_ID="phash-v1-256-exif-luma"
def get_spec(spec_id):
    if spec_id not in SPECS: raise ValueError(f"Unknown fingerprint spec: {spec_id}")
    return SPECS[spec_id]
