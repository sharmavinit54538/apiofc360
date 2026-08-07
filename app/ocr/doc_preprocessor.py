"""Image preprocessing module for Document Intelligence OCR pipeline.

Enhances document scans/images using OpenCV to maximize OCR accuracy:
- Deskew (rotation correction)
- Denoise (Gaussian/Bilateral blur)
- Contrast Enhancement (CLAHE)
- Shadow Removal & Background Cleaning
- Perspective Correction (four-point transform for camera captures)
- Sharpening
- Adaptive Threshold Binarization
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("opencv-python-headless not available — using raw images")


class DocumentPreprocessor:
    """Orchestrates OpenCV CV-operations to preprocess and clean documents for OCR."""

    def __init__(
        self,
        *,
        deskew: bool = True,
        denoise: bool = True,
        enhance_contrast: bool = True,
        remove_shadows: bool = True,
        correct_perspective: bool = True,
        sharpen: bool = True,
        binarize: bool = True,
    ) -> None:
        self.deskew = deskew
        self.denoise = denoise
        self.enhance_contrast = enhance_contrast
        self.remove_shadows = remove_shadows
        self.correct_perspective = correct_perspective
        self.sharpen = sharpen
        self.binarize = binarize

    def preprocess_image(self, file_path: str, output_path: Optional[str] = None) -> str:
        """Read, process, and write the document image. Returns path of processed file."""
        if not CV2_AVAILABLE:
            return file_path

        try:
            img = cv2.imread(file_path)
            if img is None:
                logger.error("Failed to load document image: %s", file_path)
                return file_path

            processed = self.preprocess_array(img)

            if output_path is None:
                base, ext = os.path.splitext(file_path)
                output_path = f"{base}_doc_preprocessed{ext}"

            cv2.imwrite(output_path, processed)
            return output_path
        except Exception as exc:
            logger.error("Document preprocessing failed: %s", exc)
            return file_path

    def preprocess_array(self, img: "np.ndarray") -> "np.ndarray":
        """Process a numpy image array using CV2 pipeline."""
        if not CV2_AVAILABLE:
            return img

        # Step 1: Rescale if too small (OCR needs at least 1500px width/height)
        img = self._rescale_if_small(img)

        # Step 2: Perspective Correction (for skewed phone camera snaps)
        if self.correct_perspective:
            img = self._correct_perspective(img)

        # Step 3: Denoise
        if self.denoise:
            img = self._denoise(img)

        # Step 4: Shadow Removal
        if self.remove_shadows:
            img = self._remove_shadows(img)

        # Step 5: Deskew / Rotation correction
        if self.deskew:
            img = self._deskew(img)

        # Step 6: Contrast Enhancement
        if self.enhance_contrast:
            img = self._enhance_contrast(img)

        # Step 7: Sharpen
        if self.sharpen:
            img = self._sharpen(img)

        # Step 8: Binarize
        if self.binarize:
            img = self._binarize(img)

        return img

    # ------------------------------------------------------------------
    # Image cleaning internals
    # ------------------------------------------------------------------

    @staticmethod
    def _rescale_if_small(img: "np.ndarray", target_w: int = 1600) -> "np.ndarray":
        h, w = img.shape[:2]
        if w < target_w:
            scale = target_w / w
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return img

    @staticmethod
    def _correct_perspective(img: "np.ndarray") -> "np.ndarray":
        """Find doc outline, apply perspective warp to flatten snapshot."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
        # Blur to remove noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        # Edge detection
        edged = cv2.Canny(blurred, 75, 200)

        # Find contours
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

        doc_contour = None
        for c in contours:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                doc_contour = approx
                break

        if doc_contour is None:
            return img  # fallback if no quadrilateral contour found

        # 4-point transform
        pts = doc_contour.reshape(4, 2)
        rect = np.zeros((4, 2), dtype="float32")

        # Top-left has smallest sum, bottom-right has largest sum
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        # Top-right has smallest difference, bottom-left has largest difference
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]

        (tl, tr, br, bl) = rect
        # Compute width & height of flattened document
        width_a = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        width_b = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        max_w = max(int(width_a), int(width_b))

        height_a = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        height_b = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        max_h = max(int(height_a), int(height_b))

        dst = np.array([
            [0, 0],
            [max_w - 1, 0],
            [max_w - 1, max_h - 1],
            [0, max_h - 1]
        ], dtype="float32")

        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(img, M, (max_w, max_h))
        return warped

    @staticmethod
    def _denoise(img: "np.ndarray") -> "np.ndarray":
        if len(img.shape) == 2:
            return cv2.fastNlMeansDenoising(img, h=7)
        return cv2.fastNlMeansDenoisingColored(img, h=7, hColor=7)

    @staticmethod
    def _remove_shadows(img: "np.ndarray") -> "np.ndarray":
        """Remove uneven illumination using dilation and median blur."""
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
    def _deskew(img: "np.ndarray") -> "np.ndarray":
        """Determine skew angle and rotate."""
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

        # Don't rotate for trivial angles (<0.5) or excessive (>35)
        if abs(angle) < 0.5 or abs(angle) > 35:
            return img

        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    @staticmethod
    def _enhance_contrast(img: "np.ndarray") -> "np.ndarray":
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        if len(img.shape) == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = clahe.apply(l)
            return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        return clahe.apply(img)

    @staticmethod
    def _sharpen(img: "np.ndarray") -> "np.ndarray":
        # Sharpening kernel
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        return cv2.filter2D(img, -1, kernel)

    @staticmethod
    def _binarize(img: "np.ndarray") -> "np.ndarray":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
