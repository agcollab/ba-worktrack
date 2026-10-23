"""Errors raised by services when a business rule is broken.

Routers turn them into a friendly message (HTML) or a 400/403/404 response (API).
"""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404


class Forbidden(ServiceError):
    status_code = 403
