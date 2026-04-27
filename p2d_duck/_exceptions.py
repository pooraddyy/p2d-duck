class DuckChatError(Exception):
    pass


class ChallengeError(DuckChatError):
    pass


class RateLimitError(DuckChatError):
    pass


class ConversationLimitError(DuckChatError):
    pass


class APIError(DuckChatError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
