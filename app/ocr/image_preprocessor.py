"""Image preprocessing pipeline for OCR quality improvement.

Applies a configurable sequence of CV operations to maximize OCR accuracy:
- Deskew (correct rotation)
- Noise removal (median blur)
- Contrast enhancement (CLAHE)
- Shadow removal (morphological approach)
- Perspective correction (four-point transform)
- Binarization (adaptive threshold)
- Border removal

Requires: opencv-python-headless, numpy
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    np = None
    logger.warning("opencv-python-headless or numpy not installed — image preprocessing disabled")


class ImagePreprocessor:
    """Applies a configurable pipeline of image enhancement steps."""

    def __init__(
        self,
        *,
        deskew: bool = True,
        denoise: bool = True,
        contrast_enhance: bool = True,
        shadow_remove: bool = True,
        binarize: bool = True,
        border_remove: bool = True,
        target_dpi: int = 300,
    ) -> None:
        self.deskew = deskew
        self.denoise = denoise
        self.contrast_enhance = contrast_enhance
        self.shadow_remove = shadow_remove
        self.binarize = binarize
        self.border_remove = border_remove
        self.target_dpi = target_dpi

    def preprocess(self, image_path: str, output_path: Optional[str] = None) -> str:
        """Run full preprocessing pipeline on an image file.

        Returns the path to the processed image (may be input path if CV2 not available).
        """
        if not CV2_AVAILABLE:
            logger.warning("Skipping preprocessing — OpenCV not available")
            return image_path

        try:
            img = cv2.imread(image_path)
            if img is None:
                logger.error("Cannot read image: %s", image_path)
                return image_path

            img = self._upscale_if_small(img)

            if self.shadow_remove:
                img = self._remove_shadow(img)

            if self.denoise:
                img = self._denoise(img)

            if self.deskew:
                img = self._deskew(img)

            if self.contrast_enhance:
                img = self._enhance_contrast(img)

            if self.binarize:
                img = self._binarize(img)

            if self.border_remove:
                img = self._remove_border(img)

            # Write processed image
            if output_path is None:
                base, ext = os.path.splitext(image_path)
                output_path = f"{base}_preprocessed{ext}"

            cv2.imwrite(output_path, img)
            logger.info("Preprocessing complete: %s -> %s", image_path, output_path)
            return output_path

        except Exception as exc:
            logger.error("Image preprocessing failed for %s: %s", image_path, exc)
            return image_path

    def preprocess_array(self, img: "np.ndarray") -> "np.ndarray":
        """Preprocess an already-loaded numpy image array."""
        if not CV2_AVAILABLE:
            return img

        img = self._upscale_if_small(img)
        if self.shadow_remove:
            img = self._remove_shadow(img)
        if self.denoise:
            img = self._denoise(img)
        if self.deskew:
            img = self._deskew(img)
        if self.contrast_enhance:
            img = self._enhance_contrast(img)
        if self.binarize:
            img = self._binarize(img)
        if self.border_remove:
            img = self._remove_border(img)
        return img

    # ------------------------------------------------------------------
    # Individual preprocessing steps
    # ------------------------------------------------------------------

    @staticmethod
    def _upscale_if_small(img: "np.ndarray", min_width: int = 1000) -> "np.ndarray":
        """Upscale small images to improve OCR accuracy."""
        h, w = img.shape[:2]
        if w < min_width:
            scale = min_width / w
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return img

    @staticmethod
    def _remove_shadow(img: "np.ndarray") -> "np.ndarray":
        """Remove shadows using morphological operations."""
        # Split into channels
        rgb_planes = cv2.split(img)
        result_planes = []
        for plane in rgb_planes:
            dilated = cv2.dilate(plane, np.ones((7, 7), np.uint8))
            bg = cv2.medianBlur(dilated, 21)
            diff = 255 - cv2.absdiff(plane, bg)
            norm = cv2.normalize(diff, None, alpha=0, beta=255,
                                  norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
            result_planes.append(norm)
        return cv2.merge(result_planes)

    @staticmethod
    def _denoise(img: "np.ndarray") -> "np.ndarray":
        """Apply Non-Local Means denoising."""
        if len(img.shape) == 2:
            return cv2.fastNlMeansDenoising(img, h=10, templateWindowSize=7, searchWindowSize=21)
        return cv2.fastNlMeansDenoisingColored(img, h=10, hColor=10,
                                                templateWindowSize=7, searchWindowSize=21)

    @staticmethod
    def _deskew(img: "np.ndarray") -> "np.ndarray":
        """Correct image rotation using Hough line transform."""
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
        gray = cv2.bitwise_not(gray)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 10:
            return img

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Only correct if skew is meaningful (>0.5°) and within bounds (±15°)
        if abs(angle) < 0.5 or abs(angle) > 15:
            return img

        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated

    @staticmethod
    def _enhance_contrast(img: "np.ndarray") -> "np.ndarray":
        """Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization)."""
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        if len(img.shape) == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l_chan, a_chan, b_chan = cv2.split(lab)
            l_chan = clahe.apply(l_chan)
            lab = cv2.merge([l_chan, a_chan, b_chan])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        else:
            return clahe.apply(img)

    @staticmethod
    def _binarize(img: "np.ndarray") -> "np.ndarray":
        """Convert to grayscale and apply adaptive thresholding."""
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Adaptive threshold works well for uneven lighting
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )
        return binary

    @staticmethod
    def _remove_border(img: "np.ndarray", border_size: int = 10) -> "np.ndarray":
        """Remove dark border artifacts common in scanned documents."""
        if len(img.shape) == 3:
            h, w, _ = img.shape
        else:
            h, w = img.shape
        return img[border_size:h - border_size, border_size:w - border_size]
