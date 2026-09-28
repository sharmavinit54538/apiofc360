"""
Face embedding generation and matching.

Kept behind this thin abstraction on purpose: production deployments should
plug in a real embedding model (face-recognition / InsightFace / etc). No
heavyweight CV dependency is imported at module load time, so the rest of
the backend runs and is testable without GPU/native deps installed.

To use a real model, implement `_extract_embedding` to return a fixed-length
float vector from image bytes (raise ValueError if zero or >1 faces found),
and set FACE_MODEL_NAME accordingly.
"""
import hashlib
import json
import math

FACE_MODEL_NAME = "eduflow-embedding-v1"
EMBEDDING_DIM = 128


def _extract_embedding(image_bytes: bytes) -> list[float]:
    """
    Deterministic placeholder embedding derived from image content.

    Replace this with a real face-detection + embedding model before
    production use — this stub does NOT actually detect or verify faces,
    it only produces a stable-but-meaningless vector so the enrollment/
    recognition API contract can be built, tested, and wired end-to-end.
    """
    if not image_bytes:
        raise ValueError("empty image")
    digest = hashlib.sha256(image_bytes).digest()
    vals = []
    for i in range(EMBEDDING_DIM):
        b = digest[i % len(digest)]
        vals.append((b / 255.0) * 2 - 1)
    return vals


def average_embeddings(embeddings: list[list[float]]) -> list[float]:
    n = len(embeddings)
    dim = len(embeddings[0])
    return [sum(e[i] for e in embeddings) / n for i in range(dim)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def generate_embedding(image_bytes: bytes) -> list[float]:
    return _extract_embedding(image_bytes)


def serialize(embedding: list[float]) -> str:
    return json.dumps(embedding)


def deserialize(raw: str) -> list[float]:
    return json.loads(raw)
