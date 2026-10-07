# Implementation references

The implementation was cross-checked against the same families of mature/open-source work identified in the PRD:

- FAISS — native binary Hamming indexes (`IndexBinaryFlat`, `IndexBinaryHNSW`): https://github.com/facebookresearch/faiss
- NGT — persisted neighborhood graph with Byte objects and Hamming distance: https://github.com/NGT-labs/NGT
- ImageHash — pHash bit construction / Hamming-style comparison reference: https://github.com/JohannesBuchner/imagehash
- imagededup — practical perceptual-hash duplicate workflows and multiprocessing patterns: https://github.com/idealo/imagededup
- Czkawka/Krokiet — real-world cached image hashes and duplicate-review UX: https://github.com/qarmin/czkawka

ImageDupe does not copy these projects' architecture wholesale. The PRD-specific invariants—unique fingerprint buckets, exact Hamming reranking, immutable generations, separate SHA-256 identity, and benchmarked ANN recall—remain authoritative.
