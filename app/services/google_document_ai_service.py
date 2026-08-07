"""Google Document AI Service wrapper for Document AI Process API."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import status

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class GoogleDocumentAIService:
    """Service encapsulating interactions with Google Cloud Document AI API."""

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        processor_id: str | None = None,
        credentials_file: str | None = None,
    ) -> None:
        self.project_id = project_id or settings.GOOGLE_PROJECT_ID
        self.location = location or settings.GOOGLE_LOCATION or "us"
        self.processor_id = processor_id or settings.GOOGLE_PROCESSOR_ID
        self.credentials_file = credentials_file or settings.GOOGLE_APPLICATION_CREDENTIALS

        if self.credentials_file and os.path.exists(self.credentials_file):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(self.credentials_file)

    def validate_configuration(self) -> None:
        """Ensure all required Google Document AI parameters are configured."""
        missing = []
        if not self.project_id:
            missing.append("GOOGLE_PROJECT_ID")
        if not self.processor_id:
            missing.append("GOOGLE_PROCESSOR_ID")
        if not self.credentials_file and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")

        if missing:
            msg = f"Google Document AI is unconfigured. Missing environment variable(s): {', '.join(missing)}."
            logger.error("Configuration error: %s", msg)
            raise AppException(
                message=msg,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    async def process_document(self, file_bytes: bytes, mime_type: str) -> dict[str, Any]:
        """Send raw document bytes to Google Document AI Process API and return raw result dict."""
        self.validate_configuration()

        try:
            from google.cloud import documentai_v1 as documentai
            from google.api_core.client_options import ClientOptions
            from google.api_core.exceptions import (
                GoogleAPIError,
                InvalidArgument,
                NotFound,
                PermissionDenied,
                ResourceExhausted,
                ServiceUnavailable,
            )
        except ImportError:
            msg = "Python package 'google-cloud-documentai' is not installed in the environment."
            logger.error("Dependency error: %s", msg)
            raise AppException(
                message=msg,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        client_options = ClientOptions(
            api_endpoint=f"{self.location}-documentai.googleapis.com"
        )
        processor_name = f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"

        raw_document = documentai.RawDocument(
            content=file_bytes,
            mime_type=mime_type,
        )

        request = documentai.ProcessRequest(
            name=processor_name,
            raw_document=raw_document,
        )

        logger.info("Sending document OCR request to Google Document AI processor %s (location: %s)", processor_name, self.location)
        start_time = time.time()

        # Execute call with retry logic for transient network failures
        max_retries = 3
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                # Wrap synchronous client call in asyncio thread executor
                loop = asyncio.get_running_loop()

                def _call_api():
                    client = documentai.DocumentProcessorServiceClient(client_options=client_options)
                    return client.process_document(request=request)

                result = await loop.run_in_executor(None, _call_api)
                processing_time_ms = round((time.time() - start_time) * 1000, 2)
                logger.info("Google Document AI OCR completed in %s ms", processing_time_ms)

                document = result.document
                # Return document object & execution time
                return {
                    "document": document,
                    "processing_time_ms": processing_time_ms,
                    "status_code": 200,
                }
            except (ServiceUnavailable, TimeoutError) as exc:
                last_exception = exc
                logger.warning("Attempt %s/%s failed with transient error: %s. Retrying...", attempt, max_retries, exc)
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
            except InvalidArgument as exc:
                logger.error("Google Document AI InvalidArgument: %s", exc)
                raise AppException(
                    message=f"Document AI error: Invalid document format or arguments. Details: {exc.message}",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            except PermissionDenied as exc:
                logger.error("Google Document AI PermissionDenied: %s", exc)
                raise AppException(
                    message="Google Document AI authentication failed or permission denied. Check service account credentials.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            except NotFound as exc:
                logger.error("Google Document AI NotFound: %s", exc)
                raise AppException(
                    message=f"Google Document AI Processor '{self.processor_id}' not found in location '{self.location}'.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            except ResourceExhausted as exc:
                logger.error("Google Document AI QuotaExceeded: %s", exc)
                raise AppException(
                    message="Google Document AI API quota or rate limit exceeded. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            except GoogleAPIError as exc:
                logger.error("Google Document API error: %s", exc)
                raise AppException(
                    message=f"Google Document AI API error: {getattr(exc, 'message', str(exc))}",
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )
            except Exception as exc:
                logger.exception("Unexpected error calling Google Document AI API: %s", exc)
                raise AppException(
                    message=f"Document OCR processing error: {str(exc)}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        if last_exception:
            raise AppException(
                message=f"Document AI service unavailable after {max_retries} attempts: {str(last_exception)}",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            )
