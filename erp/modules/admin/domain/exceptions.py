"""Public domain failures for M1 authentication."""


class AuthenticationError(Exception):
    """Base failure safe to translate at the API boundary."""


class InvalidCredentialsError(AuthenticationError):
    """Credentials are invalid without disclosing which check failed."""


class InvalidSessionError(AuthenticationError):
    """A refresh or logout token does not identify an active session."""


class AuthorizationError(Exception):
    """Base failure for authorization policy and registry operations."""


class DuplicatePermissionError(AuthorizationError):
    """A permission code was registered more than once."""


class PermissionNotRegisteredError(AuthorizationError):
    """A permission code is absent from the official registry."""


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "DuplicatePermissionError",
    "InvalidCredentialsError",
    "InvalidSessionError",
    "PermissionNotRegisteredError",
]
