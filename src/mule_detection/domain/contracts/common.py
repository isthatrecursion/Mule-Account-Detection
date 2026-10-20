from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, ClassVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError

from mule_detection.domain.errors import MESSAGES, DomainError, ErrorCode


def violation(code: ErrorCode) -> PydanticCustomError:
    return PydanticCustomError(code.value, MESSAGES[code])


def utc(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise violation(ErrorCode.TIMESTAMP_INVALID) from None
    if not isinstance(value, datetime):
        raise violation(ErrorCode.TIMESTAMP_INVALID)
    if value.utcoffset() is None:
        raise violation(ErrorCode.TIMESTAMP_NAIVE)
    if value.utcoffset() != timedelta(0):
        raise violation(ErrorCode.TIMESTAMP_INVALID)
    return value.astimezone(UTC)


def count(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and value < 0:
        raise violation(ErrorCode.COUNT_INVALID)
    return value


UtcTime = Annotated[datetime, BeforeValidator(utc)]
Nonnegative = Annotated[StrictInt, BeforeValidator(count), Field(ge=0)]
Positive = Annotated[StrictInt, Field(gt=0)]
Text = Annotated[StrictStr, Field(min_length=1, max_length=512)]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class ValueModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
        validate_default=True,
        revalidate_instances="always",
    )


class Contract(ValueModel):
    VERSION: ClassVar[str]

    @model_validator(mode="before")
    @classmethod
    def known_version(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and "contract_version" in value
            and value["contract_version"] != cls.VERSION
        ):
            raise violation(ErrorCode.CONTRACT_VERSION)
        return value


def parse_contract[T: ValueModel](model: type[T], value: Any) -> T:
    """The public parsing boundary: no rejected input or Pydantic diagnostics escape."""
    try:
        if isinstance(value, (str, bytes)):

            def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for name, item in pairs:
                    if name in result:
                        raise DomainError(ErrorCode.SCHEMA_MISMATCH)
                    result[name] = item
                return result

            def reject_constant(token: str) -> Any:
                raise DomainError(ErrorCode.VALUE_INVALID)

            value = json.loads(
                value, object_pairs_hook=unique_pairs, parse_constant=reject_constant
            )
        return model.model_validate(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise DomainError(ErrorCode.CONTRACT_INVALID) from None
    except ValidationError as error:
        first = error.errors(include_input=False, include_context=False)[0]["type"]
        try:
            code = ErrorCode(first)
        except ValueError:
            code = ErrorCode.CONTRACT_INVALID
        raise DomainError(code) from None


def canonical_hash(value: ValueModel | dict[str, Any]) -> str:
    import hashlib

    payload = value.model_dump(mode="json") if isinstance(value, ValueModel) else value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
