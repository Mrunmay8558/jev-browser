"""Public errors deliberately exclude keys, provider bodies, and request contents."""


class EvaluationError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code
