"""Typed errors exposed by the core and CLI."""


class WindAgentError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(WindAgentError):
    """Configuration is invalid or internally inconsistent."""


class ContractNotConfirmedError(WindAgentError):
    """Strict operation was requested with an unresolved data contract."""


class NotImplementedCommandError(WindAgentError):
    """A command belongs to a later implementation stage."""
