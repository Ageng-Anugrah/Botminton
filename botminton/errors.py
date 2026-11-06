"""Exception types used across the bot."""


class BotmintonError(Exception):
    """Base class for all bot errors."""


class ConfigError(BotmintonError):
    """Raised when required configuration is missing or invalid."""


class AyoAPIError(BotmintonError):
    """Raised when the ayo.co.id API cannot be queried or parsed."""


class StoreError(BotmintonError):
    """Raised when event data cannot be loaded or saved."""


class EventNotFoundError(StoreError):
    """Raised when an event ID no longer exists in the store."""

    def __init__(self, event_id: str) -> None:
        super().__init__("Event ini sudah tidak ada atau sudah dihapus.")
        self.event_id = event_id


class ValidationError(BotmintonError):
    """Raised when user-provided event data is invalid."""


class ParticipantError(BotmintonError):
    """Base class for participant-related errors."""


class ParticipantNotFoundError(ParticipantError):
    """Raised when a participant cannot be found in an event."""

    def __init__(self, message: str = "Peserta tidak ditemukan di event ini.") -> None:
        super().__init__(message)


class DuplicateParticipantError(ParticipantError):
    """Raised when a participant name is already present in an event."""


class AlreadyJoinedError(ParticipantError):
    """Raised when a user is already on the attendance list."""


class AlreadyPaidError(ParticipantError):
    """Raised when a participant is already marked as paid."""


class NotPaidError(ParticipantError):
    """Raised when a participant is not marked as paid."""


class ActionNotAllowedError(ParticipantError):
    """Raised when a user tries to change a payment they do not own."""
