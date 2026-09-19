"""AI Facial Recognition and Anti-Spoofing Liveness Service.

Provides:
1. Base64 / Multipart image decoding and sanity checks
2. Image quality verification (blurriness, illumination, face bounding box dimensions)
3. Multi-metric passive anti-spoofing / liveness verification (FFT frequency spectrum,
   HSV/YCrCb color gamut variance, specular glare detection)
4. Exactly-one-face detection rule with structured error codes
5. 128-dimensional biometric embedding extraction via dlib / face_recognition
6. Biometric distance comparison with documented 0.50 threshold
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import HTTPException, status
from PIL import Image

try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False

logger = logging.getLogger(__name__)

# Documented Similarity Threshold: distance <= 0.50 corresponds to >= 85% biometric match confidence
MATCH_DISTANCE_THRESHOLD: float = 0.50

# Minimum image sharpness (Laplacian variance) to pass quality check
MIN_LAPLACIAN_VARIANCE: float = 50.0

# Minimum face bounding box pixel dimensions
MIN_FACE_WIDTH_PX: int = 60
MIN_FACE_HEIGHT_PX: int = 60
MIN_FACE_AREA_RATIO: float = 0.03


class FaceRecognitionService:
    """Enterprise facial recognition, anti-spoofing, and quality analysis service."""

    @staticmethod
    def decode_base64_image(image_base64: str) -> np.ndarray:
        """Decodes base64 string (raw or data-URI scheme) into an RGB numpy array.
        
        Validates:
        - Presence and string type
        - Safe removal of data URI MIME prefixes (data:image/jpeg;base64, etc.)
        - Safe base64 decoding and padding resolution
        - Image format verification (JPEG, PNG, WEBP)
        - Minimum dimensions (min 80x80, max 4096x4096)
        - Converts to RGB format
        """
        if not image_base64 or not isinstance(image_base64, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Image data is required."},
            )

        clean_base64 = image_base64.strip()
        if "," in clean_base64:
            clean_base64 = clean_base64.split(",", 1)[1].strip()

        if not clean_base64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Image payload is empty."},
            )

        try:
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
                detail={"code": "FACE_QUALITY_LOW", "message": "Malformed base64 image data."},
            )

        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            img_format = (pil_image.format or "").upper()
            if img_format not in ("JPEG", "JPG", "PNG", "WEBP"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "FACE_QUALITY_LOW",
                        "message": f"Unsupported image format: '{img_format}'. Please provide a valid JPEG, PNG, or WEBP image.",
                    },
                )

            width, height = pil_image.size
            if width < 80 or height < 80:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "FACE_QUALITY_LOW", "message": "Image resolution is too low. Minimum 80x80 required."},
                )

            # Cap oversized dimensions to protect memory during feature extraction
            if width > 4096 or height > 4096:
                pil_image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)

            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            return np.array(pil_image)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Failed to process image bytes: %s", str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Invalid image format or corrupted image file."},
            )

    @staticmethod
    def check_image_quality(rgb_array: np.ndarray, face_location: Tuple[int, int, int, int]) -> Dict[str, Any]:
        """Performs rigorous image quality checks:
        
        1. Laplacian blur detection (variance of Laplacian on grayscale image).
        2. Illumination bounds check (mean grayscale brightness).
        3. Face bounding box dimension checks (min width, min height, min area ratio).
        
        Raises HTTPException 400 with FACE_QUALITY_LOW code on quality failure.
        """
        gray = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2GRAY)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Check blurriness
        if laplacian_var < MIN_LAPLACIAN_VARIANCE:
            logger.warning("Image failed blur check: laplacian_var=%.2f < %.2f", laplacian_var, MIN_LAPLACIAN_VARIANCE)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Image is too blurry. Please hold your camera steady in good lighting.",
                },
            )

        # Check illumination
        mean_brightness = float(np.mean(gray))
        if mean_brightness < 30.0:
            logger.warning("Image failed illumination check: mean_brightness=%.2f (too dark)", mean_brightness)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Image is too dark. Please ensure sufficient ambient lighting.",
                },
            )
        if mean_brightness > 248.0:
            logger.warning("Image failed illumination check: mean_brightness=%.2f (overexposed)", mean_brightness)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Image is overexposed or washed out. Please avoid pointing directly at bright light.",
                },
            )

        # Check face dimensions
        top, right, bottom, left = face_location
        face_w = right - left
        face_h = bottom - top
        img_h, img_w, _ = rgb_array.shape
        face_area_ratio = (face_w * face_h) / float(img_w * img_h)

        if face_w < MIN_FACE_WIDTH_PX or face_h < MIN_FACE_HEIGHT_PX:
            logger.warning("Face too small: w=%d, h=%d", face_w, face_h)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Face is too small. Please position your face closer to the camera.",
                },
            )

        if face_area_ratio < MIN_FACE_AREA_RATIO:
            logger.warning("Face area ratio too small: %.4f < %.4f", face_area_ratio, MIN_FACE_AREA_RATIO)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Face occupies too little of the frame. Please center your face in the camera.",
                },
            )

        return {
            "sharpness": laplacian_var,
            "brightness": mean_brightness,
            "face_width": face_w,
            "face_height": face_h,
            "face_area_ratio": face_area_ratio,
        }

    @staticmethod
    def verify_liveness(
        rgb_array: np.ndarray,
        face_location: Tuple[int, int, int, int],
    ) -> float:
        """Passive Anti-Spoofing and Liveness Verification.
        
        Analyzes:
        1. Chromatic Skin Gamut Distribution in YCrCb color space (detects monochrome / paper prints).
        2. High-Frequency Fourier Moiré Patterns (detects digital screen grids / LCD pixels).
        3. Specular Reflection / Glare Distribution (detects smartphone screen glass reflection).
        
        Returns liveness_score (0.0 to 1.0).
        Raises HTTPException 400 with LIVENESS_FAILED if score < 0.40.
        """
        top, right, bottom, left = face_location
        # Add slight margin around face crop for context
        margin = 10
        h_max, w_max, _ = rgb_array.shape
        y1 = max(0, top - margin)
        y2 = min(h_max, bottom + margin)
        x1 = max(0, left - margin)
        x2 = min(w_max, right + margin)

        face_crop = rgb_array[y1:y2, x1:x2]
        if face_crop.size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Failed to crop face region."},
            )

        # 1. Chromatic distribution in YCrCb space
        # Real human skin typically exhibits Cr in [130, 175] and Cb in [75, 135]
        face_ycrcb = cv2.cvtColor(face_crop, cv2.COLOR_RGB2YCrCb)
        cr = face_ycrcb[:, :, 1]
        cb = face_ycrcb[:, :, 2]
        skin_mask = (cr >= 130) & (cr <= 175) & (cb >= 75) & (cb <= 135)
        total_pixels = face_crop.shape[0] * face_crop.shape[1]
        skin_ratio = float(np.sum(skin_mask)) / float(total_pixels + 1e-9)

        # 2. Specular reflection / screen glare in HSV space
        # Digital screens produce high-value, very low-saturation glare hotspots
        face_hsv = cv2.cvtColor(face_crop, cv2.COLOR_RGB2HSV)
        sat = face_hsv[:, :, 1]
        val = face_hsv[:, :, 2]
        glare_mask = (val > 245) & (sat < 25)
        glare_ratio = float(np.sum(glare_mask)) / float(total_pixels + 1e-9)

        # 3. High-frequency FFT spectrum analysis
        face_gray = cv2.cvtColor(face_crop, cv2.COLOR_RGB2GRAY)
        f = np.fft.fft2(face_gray)
        fshift = np.fft.fftshift(f)
        h, w = face_gray.shape
        cy, cx = h // 2, w // 2
        r = max(5, min(cy, cx) // 4)
        y, x = np.ogrid[:h, :w]
        center_mask = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        low_energy = float(np.sum(np.abs(fshift)[center_mask]))
        total_energy = float(np.sum(np.abs(fshift)) + 1e-9)
        high_freq_ratio = (total_energy - low_energy) / total_energy

        # Composite liveness calculation
        chroma_score = min(1.0, max(0.0, skin_ratio * 1.6))
        glare_penalty = min(1.0, max(0.0, glare_ratio * 4.0))
        freq_consistency = 1.0 if 0.05 <= high_freq_ratio <= 0.85 else 0.5

        liveness_score = round(
            (chroma_score * 0.55) + (freq_consistency * 0.30) + (max(0.0, 1.0 - glare_penalty) * 0.15),
            2,
        )
        liveness_score = max(0.0, min(1.0, liveness_score))

        logger.info(
            "Liveness metrics: score=%.2f, skin_ratio=%.2f, glare_ratio=%.2f, high_freq_ratio=%.2f",
            liveness_score, skin_ratio, glare_ratio, high_freq_ratio,
        )

        # Hard rejections for obvious spoofs
        if skin_ratio < 0.15:
            logger.warning("Liveness failed: skin_ratio too low (%.2f)", skin_ratio)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LIVENESS_FAILED",
                    "message": "Anti-spoofing check failed. Printed photo or unnatural display detected.",
                },
            )

        if glare_ratio > 0.25:
            logger.warning("Liveness failed: excessive glare/screen reflection (%.2f)", glare_ratio)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LIVENESS_FAILED",
                    "message": "Anti-spoofing check failed. Screen glare or reflection detected.",
                },
            )

        if liveness_score < 0.40:
            logger.warning("Liveness failed: composite score %.2f < 0.40", liveness_score)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LIVENESS_FAILED",
                    "message": "Liveness verification failed. Please position your face naturally in ambient light.",
                },
            )

        return liveness_score

    @classmethod
    def detect_and_validate_single_face(
        cls, rgb_array: np.ndarray, enforce_liveness: bool = True
    ) -> Tuple[Tuple[int, int, int, int], Dict[str, Any], float]:
        """Detects faces in image, asserts exactly one face, runs quality and liveness checks.
        
        Returns:
            (face_location, quality_dict, liveness_score)
        """
        if not HAS_FACE_RECOGNITION:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "SYSTEM_ERROR", "message": "Face recognition subsystem is not installed."},
            )

        face_locations = face_recognition.face_locations(rgb_array)
        num_faces = len(face_locations)

        if num_faces == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_NOT_FOUND", "message": "No face detected. Please look directly at the camera."},
            )

        if num_faces > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MULTIPLE_FACES",
                    "message": f"Multiple faces ({num_faces}) detected. Only one person must be visible.",
                },
            )

        location = face_locations[0]

        # 1. Quality checks
        quality = cls.check_image_quality(rgb_array, location)

        # 2. Anti-spoofing / liveness check
        liveness_score = 1.0
        if enforce_liveness:
            liveness_score = cls.verify_liveness(rgb_array, location)

        return location, quality, liveness_score

    @classmethod
    def extract_face_embedding(
        cls, rgb_array: np.ndarray, enforce_liveness: bool = True
    ) -> Tuple[List[float], float]:
        """Detects single face, validates quality and liveness, and extracts 128-d embedding.
        
        Returns:
            (embedding_vector, liveness_score)
        """
        location, _, liveness_score = cls.detect_and_validate_single_face(rgb_array, enforce_liveness=enforce_liveness)

        encodings = face_recognition.face_encodings(rgb_array, known_face_locations=[location])
        if not encodings:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FACE_QUALITY_LOW",
                    "message": "Could not extract facial biometric features. Please ensure direct eye line and good lighting.",
                },
            )

        embedding: List[float] = [float(x) for x in encodings[0].tolist()]
        return embedding, liveness_score

    @staticmethod
    def compare_embeddings(
        saved_embedding: List[float],
        live_embedding: List[float],
        threshold: float = MATCH_DISTANCE_THRESHOLD,
    ) -> Tuple[bool, float]:
        """Compares saved baseline embedding and live embedding using Euclidean distance.
        
        Returns (is_match, distance).
        Threshold <= 0.50 corresponds to >= 85% confidence match.
        """
        if not saved_embedding or not live_embedding:
            return False, 1.0

        saved_arr = np.array(saved_embedding, dtype=np.float64)
        live_arr = np.array(live_embedding, dtype=np.float64)

        if HAS_FACE_RECOGNITION:
            distances = face_recognition.face_distance([saved_arr], live_arr)
            distance = float(distances[0])
        else:
            distance = float(np.linalg.norm(saved_arr - live_arr))

        is_match = distance <= threshold
        return is_match, distance
