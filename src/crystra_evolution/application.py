from typing import Protocol

from crystra_evolution.api.models import ComputeRequest, ComputeResponse


class UpstreamUnavailable(RuntimeError):
    """A retryable Evidence transport or availability failure."""


class UpstreamContractMismatch(RuntimeError):
    """A non-retryable incompatible Evidence response."""


class ResolutionBoundExceeded(RuntimeError):
    """A non-retryable configured Evolution resolution safety bound."""


class ComputeService(Protocol):
    async def compute(self, request: ComputeRequest) -> ComputeResponse: ...
