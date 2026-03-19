class CircuitBreaker:
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._last_error_signature = ""

    def record_attempt(self, success: bool, error_signature: str = "") -> None:
        if success:
            self._consecutive_failures = 0
            self._last_error_signature = ""
        else:
            # Different error means progress — reset counter
            if error_signature and error_signature != self._last_error_signature:
                self._consecutive_failures = 1
                self._last_error_signature = error_signature
            else:
                self._consecutive_failures += 1
                self._last_error_signature = error_signature

    def is_tripped(self) -> bool:
        return self._consecutive_failures >= self.MAX_RETRIES

    @property
    def attempts(self) -> int:
        return self._consecutive_failures

    def reset(self) -> None:
        self._consecutive_failures = 0
        self._last_error_signature = ""
