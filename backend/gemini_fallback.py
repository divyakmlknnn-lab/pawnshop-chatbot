import logging
import re
import time
from typing import Callable, TypeVar

from google.genai import errors as genai_errors

from formatting import wrap_gemini_fallback_reply
from intent import INTENT_TO_ACTION, UNKNOWN, IntentClassification

logger = logging.getLogger("telleriq.chat")

GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_BASE_DELAY_SEC = 1.0

T = TypeVar("T")

TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_STATUSES = frozenset(
    {
        "UNAVAILABLE",
        "RESOURCE_EXHAUSTED",
        "INTERNAL",
        "DEADLINE_EXCEEDED",
    }
)
TRANSIENT_MESSAGE_PATTERNS = (
    r"\b503\b",
    r"unavailable",
    r"rate limit",
    r"resource exhausted",
    r"too many requests",
    r"overloaded",
    r"temporarily unavailable",
    r"service unavailable",
    r"\b429\b",
    r"high demand",
)


def is_transient_gemini_error(exc: Exception) -> bool:
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.APIError):
        if exc.code in TRANSIENT_HTTP_CODES:
            return True
        if exc.status in TRANSIENT_STATUSES:
            return True
    text = str(exc).lower()
    return any(re.search(pattern, text) for pattern in TRANSIENT_MESSAGE_PATTERNS)


def gemini_error_code(exc: Exception) -> int | None:
    if isinstance(exc, genai_errors.APIError) and exc.code is not None:
        return int(exc.code)
    match = re.search(r"\b(429|500|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def call_gemini_with_retry(
    operation: Callable[[], T],
    *,
    max_retries: int = GEMINI_MAX_RETRIES,
    base_delay_sec: float = GEMINI_RETRY_BASE_DELAY_SEC,
) -> T:
    last_exc: Exception | None = None
    total_attempts = max_retries + 1

    for attempt in range(total_attempts):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if not is_transient_gemini_error(exc):
                raise
            if attempt >= max_retries:
                break

            delay = base_delay_sec * (2 ** attempt)
            logger.warning(
                "Gemini transient error (attempt %d/%d, code=%s), retrying in %.1fs: %s",
                attempt + 1,
                total_attempts,
                gemini_error_code(exc),
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_exc is not None
    logger.error(
        "Gemini unavailable after %d attempts (last code=%s): %s",
        total_attempts,
        gemini_error_code(last_exc),
        last_exc,
    )
    raise last_exc


def _classification_for_fallback(classification: IntentClassification) -> IntentClassification:
    if classification.action or classification.intent == UNKNOWN:
        return classification
    action = INTENT_TO_ACTION.get(classification.intent)
    if not action:
        return classification
    return IntentClassification(
        intent=classification.intent,
        confidence=classification.confidence,
        action=action,
        tool=classification.tool,
        args=dict(classification.args or {}),
        customer_id=classification.customer_id,
        customer_name=classification.customer_name,
    )


def build_gemini_fallback_response(
    message: str,
    classification: IntentClassification,
    executions: list[tuple[str, dict, object]],
    *,
    execute_operational,
    response_from_executions,
    empty_fallback,
) -> dict:
    if executions:
        result = response_from_executions(classification, executions)
        if result:
            result["reply"] = wrap_gemini_fallback_reply(result["reply"])
            result["history_text"] = (
                "Answered with database fallback after Gemini was unavailable."
            )
            return result

    fallback_classification = _classification_for_fallback(classification)
    if fallback_classification.action and fallback_classification.intent != UNKNOWN:
        try:
            result = execute_operational(message, fallback_classification)
            result["reply"] = wrap_gemini_fallback_reply(result["reply"])
            result["history_text"] = (
                "Answered with database fallback after Gemini was unavailable."
            )
            return result
        except Exception:
            logger.exception("Operational fallback failed after Gemini error")

    logger.warning(
        "Gemini unavailable with no database fallback for intent=%s action=%s",
        classification.intent,
        classification.action,
    )
    return empty_fallback(classification, executions)
