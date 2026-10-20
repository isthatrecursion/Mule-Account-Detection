import re
from uuid import UUID, uuid5

from mule_detection.domain.errors import DomainError, ErrorCode

RESEARCH_NAMESPACE = UUID("672c45ae-3a4d-4ab0-8d85-636c2c15c9ea")


def research_record_key(dataset_sha256: str, original_reference: object) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", dataset_sha256):
        raise DomainError(ErrorCode.HASH_MISMATCH)
    if isinstance(original_reference, bool) or not re.fullmatch(r"[0-9]+", str(original_reference)):
        raise DomainError(ErrorCode.IDENTITY_CONFLICT)
    identity = uuid5(RESEARCH_NAMESPACE, f"{dataset_sha256.lower()}:{int(str(original_reference))}")
    return f"research:{identity}"
