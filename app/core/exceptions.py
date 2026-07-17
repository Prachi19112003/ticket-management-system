class TicketSystemException(Exception):
    """Base exception for the Ticket Management System."""
    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DatabaseException(TicketSystemException):
    """Exception raised for database operational errors."""
    pass


class CacheException(TicketSystemException):
    """Exception raised for Redis or caching operational errors."""
    pass


class StorageException(TicketSystemException):
    """Exception raised for S3 or object storage operational errors."""
    pass


class LLMException(TicketSystemException):
    """Exception raised for LLM API integration failures."""
    pass


class EmbeddingException(TicketSystemException):
    """Exception raised for embedding and classification service failures."""
    pass


class GmailException(TicketSystemException):
    """Exception raised for Gmail API integration failures."""
    pass


class ValidationException(TicketSystemException):
    """Exception raised for business validation logic failures."""
    pass
