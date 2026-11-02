"""Central approved copy and a conservative wording scan for authored UI text."""

import re


def readable(value: str) -> str:
    """Human labels never change the wire enum sent to the API."""
    return value.replace("_", " ").capitalize()


LABELS = {
    "score": "Review-priority score (ranking only)",
    "percentile": "Position in this cohort, not a probability",
    "research": "Research demonstration. Cohort/target confounding remains unresolved. Feature meanings are unverified.",
    "in_sample": "In-sample demonstration on training data; this is not evaluation evidence.",
    "unavailable": "— No usable complete assessment is available. Check the source status.",
    "conclusion": "Recording a conclusion does not create an adjudicated outcome label.",
    "provisional": "Incomplete data. This provisional result has no adverse-action authority.",
    "mock": "MOCK DATA · SYNTHETIC FIXTURES · FIXTURE IDENTITY (TEST ONLY)",
    "meaning": "Meaning unverified",
    "extension": "Not available in this build",
}

MESSAGES = {
    "UNAVAILABLE": "The API is unavailable. A pending action may have completed; check its outcome before retrying.",
    "DENIED": "Your current API permissions do not allow this action. Choose an authorized view.",
    "NOT_FOUND": "This item is unavailable in your current scope. Return to the queue.",
    "CONFLICT": "The case or request changed. Review the latest state before a new action.",
    "INVALID": "The API rejected this request. Check the required fields and upload limits.",
    "RATE_LIMITED": "The API is limiting requests. Wait before trying again.",
    "CONTRACT": "The API response does not match the supported contract. Reload or contact the deployment owner.",
    "LOGIN_REQUIRED": "Sign in again through the identity gateway to continue.",
}

FORBIDDEN_PHRASES = (
    "fraud probability",
    "probability of fraud",
    "percent chance",
    "% chance",
    "likelihood of fraud",
    "confirmed mule",
    "guilty",
    "risk-free",
    "safe account",
    "cleared",
    "no risk",
    "low risk",
    "risk reduced",
    "risk decreased",
    "risk went down",
    "case can be closed",
    "close the case because",
    "auto-restrict",
    "auto-block",
    "file report automatically",
)


def find_forbidden(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.casefold())
    return [
        p for p in FORBIDDEN_PHRASES if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", normalized)
    ]
