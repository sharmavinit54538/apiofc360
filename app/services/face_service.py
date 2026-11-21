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
    """Legacy school biometrics are unsupported; never return hash embeddings."""
    raise RuntimeError("Legacy biometric verification is unavailable. Use the HRMS attendance service.")


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
