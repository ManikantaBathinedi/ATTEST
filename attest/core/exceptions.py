"""Core exceptions for the ATTEST framework."""


class AttestError(Exception):
    """Base exception for all ATTEST errors."""


class ConfigError(AttestError):
    """Raised when configuration is invalid or missing."""


class AdapterError(AttestError):
    """Raised when an agent adapter fails to connect or communicate."""


class EvaluationError(AttestError):
    """Raised when an evaluator fails to produce a result."""


class ScenarioError(AttestError):
    """Raised when a scenario definition is invalid."""


class TimeoutError(AttestError):
    """Raised when an agent does not respond within the timeout."""


class PluginError(AttestError):
    """Raised when a plugin fails to load or execute."""


class ProtocolError(AttestError):
    """Raised when a protocol compliance check encounters an error."""
