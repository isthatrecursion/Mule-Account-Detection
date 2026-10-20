"""Server-owned version registry; payloads never supply schema paths or code."""

from types import MappingProxyType
from typing import Any

from mule_detection.domain.contracts.audit import AuditEvent
from mule_detection.domain.contracts.batch import BatchManifest
from mule_detection.domain.contracts.common import ValueModel, parse_contract
from mule_detection.domain.contracts.events import CompletenessManifest, TransactionEvent
from mule_detection.domain.contracts.evidence import Evidence
from mule_detection.domain.contracts.feature_dictionary import FeatureDictionary
from mule_detection.domain.contracts.jobs import Job
from mule_detection.domain.contracts.labels import QualifiedLabel
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.contracts.reviews import ReviewRequest
from mule_detection.domain.contracts.scores import ScoreRow
from mule_detection.domain.contracts.snapshot import QualifiedSnapshot, SourceRegistry
from mule_detection.domain.contracts.tabular import TabularSchema
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy

_MODELS = (
    BatchManifest,
    QualifiedSnapshot,
    SourceRegistry,
    TabularSchema,
    FeatureDictionary,
    QualifiedLabel,
    ModelBundle,
    ScoreRow,
    TransactionEvent,
    CompletenessManifest,
    Evidence,
    ReviewRequest,
    Job,
    AuditEvent,
    FeaturePolicy,
)
CONTRACTS = MappingProxyType({model.VERSION: model for model in _MODELS})


def resolve_contract(version: str, payload: Any) -> ValueModel:
    model = CONTRACTS.get(version)
    if model is None:
        raise DomainError(ErrorCode.CONTRACT_VERSION)
    return parse_contract(model, payload)
