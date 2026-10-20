from mule_detection.application.context import ExecutionContext
from mule_detection.domain.contracts.reviews import AuthoredReview, ReviewRequest


def author_review(request: ReviewRequest, context: ExecutionContext) -> AuthoredReview:
    """Bind server context; HTTP authentication/authorization is implemented in Phase 9."""
    return AuthoredReview(request, context.actor_id, context.correlation_id)
