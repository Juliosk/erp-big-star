"""Public domain failures for M1 authentication."""


class AuthenticationError(Exception):
    """Base failure safe to translate at the API boundary."""


class InvalidCredentialsError(AuthenticationError):
    """Credentials are invalid without disclosing which check failed."""


class InvalidSessionError(AuthenticationError):
    """A refresh or logout token does not identify an active session."""


__all__ = ["AuthenticationError", "InvalidCredentialsError", "InvalidSessionError"]
