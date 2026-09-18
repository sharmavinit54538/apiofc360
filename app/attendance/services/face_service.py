"""AI Facial Recognition Service using face_recognition and numpy.

Provides facial detection, 128-dimensional vector embedding extraction,
and biometric distance comparison for employee face attendance.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Tuple, List, Optional
import numpy as np
from PIL import Image
from fastapi import HTTPException, status

try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False

logger = logging.getLogger(__name__)

# Constants
MATCH_DISTANCE_THRESHOLD = 0.50  # Distance <= 0.50 corresponds to >= 85% confidence


class FaceRecognitionService:
    """Service handling face detection, embedding extraction, and comparison."""

    @staticmethod
    def decode_base64_image(image_base64: str) -> np.ndarray:
        """Decodes base64 string (raw or data-URI scheme) into an RGB numpy array.
        
        Validates:
        - Presence and string type
        - Safe removal of data URI MIME prefixes (data:image/jpeg;base64, etc.)
        - Safe base64 decoding and padding resolution
        - Image format verification (JPEG, PNG, WEBP)
        - Reasonable dimensions (min 60x60, max 4096x4096)
        - Converts to RGB format
        
        Raises HTTPException 400 with user-friendly messages on validation failures.
        """
        if not image_base64 or not isinstance(image_base64, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image base64 data is required.",
            )

        clean_base64 = image_base64.strip()
        # Safely remove Data URL prefix if present (e.g. data:image/jpeg;base64, or data:image/png;base64,)
        if "," in clean_base64:
            clean_base64 = clean_base64.split(",", 1)[1].strip()

        if not clean_base64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image base64 payload is empty.",
            )

        try:
            # Fix padding if necessary
            missing_padding = len(clean_base64) % 4
            if missing_padding:
                clean_base64 += "=" * (4 - missing_padding)

            image_bytes = base64.b64decode(clean_base64, validate=False)
            if not image_bytes:
                raise ValueError("Decoded image bytes are empty.")
        except Exception as exc:
            logger.warning("Failed to decode base64 string: %s", str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed base64 image data.",
            )

        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            img_format = (pil_image.format or "").upper()
            if img_format not in ("JPEG", "JPG", "PNG", "WEBP"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported image format: '{img_format}'. Please provide a valid JPEG or PNG image.",
                )

            width, height = pil_image.size
            if width < 60 or height < 60:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image resolution is too low. Please provide a clear, higher-resolution face photo.",
                )

            # Cap oversized dimensions to protect memory during feature extraction
            if width > 4096 or height > 4096:
                pil_image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)

            # Ensure RGB format for dlib / face_recognition
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            return np.array(pil_image)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Failed to process image bytes: %s", str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image format or corrupted image file.",
            )

    @staticmethod
    def extract_face_embedding(rgb_array: np.ndarray) -> List[float]:
        """Detects single face in the image and returns its 128-dimensional embedding.
        
        Enforces:
        - 0 faces detected => 400: "No face detected. Please capture your face again."
        - Multiple faces detected => 400: "Multiple faces detected. Please ensure only one person is visible."
        """
        if not HAS_FACE_RECOGNITION:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Face recognition subsystem is not installed on the server.",
            )

        # Detect face bounding box locations
        face_locations = face_recognition.face_locations(rgb_array)
        num_faces = len(face_locations)

        if num_faces == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No face detected. Please capture your face again.",
            )

        if num_faces > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple faces detected. Please ensure only one person is visible.",
            )

        # Extract 128-dimensional encodings for the detected face
        encodings = face_recognition.face_encodings(rgb_array, known_face_locations=face_locations)
        if not encodings:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract facial features. Please ensure proper lighting and look directly at the camera.",
            )

        embedding: List[float] = encodings[0].tolist()
        return embedding

    @staticmethod
    def compare_embeddings(
        saved_embedding: List[float],
        live_embedding: List[float],
        threshold: float = MATCH_DISTANCE_THRESHOLD,
    ) -> Tuple[bool, float]:
        """Compares saved baseline embedding and live embedding using face_recognition.face_distance.
        
        Returns (is_match, distance).
        Threshold <= 0.50 corresponds to >= 85% confidence match.
        """
        if not saved_embedding or not live_embedding:
            return False, 1.0

        if not HAS_FACE_RECOGNITION:
            # Fallback to Euclidean distance via numpy
            saved_vec = np.array(saved_embedding, dtype=np.float64)
            live_vec = np.array(live_embedding, dtype=np.float64)
            distance = float(np.linalg.norm(saved_vec - live_vec))
            return (distance <= threshold), distance

        saved_arr = np.array(saved_embedding, dtype=np.float64)
        live_arr = np.array(live_embedding, dtype=np.float64)

        # face_recognition.face_distance calculates Euclidean distance between 128-d face encodings
        distances = face_recognition.face_distance([saved_arr], live_arr)
        distance = float(distances[0])
        is_match = distance <= threshold

        return is_match, distance
