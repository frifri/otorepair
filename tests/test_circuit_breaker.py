"""Tests for otorepair.circuit_breaker — retry safeguard."""

from otorepair.circuit_breaker import CircuitBreaker


class TestCircuitBreakerInit:
    def test_starts_not_tripped(self):
        cb = CircuitBreaker()
        assert not cb.is_tripped()

    def test_starts_with_zero_attempts(self):
        cb = CircuitBreaker()
        assert cb.attempts == 0


class TestRecordSuccess:
    def test_success_resets_counter(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="err1")
        cb.record_attempt(success=False, error_signature="err1")
        cb.record_attempt(success=True)
        assert cb.attempts == 0
        assert not cb.is_tripped()

    def test_success_after_failures_allows_new_failures(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="e")
        cb.record_attempt(success=False, error_signature="e")
        cb.record_attempt(success=True)
        cb.record_attempt(success=False, error_signature="e")
        assert cb.attempts == 1
        assert not cb.is_tripped()


class TestRecordFailure:
    def test_consecutive_same_error_increments(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="err")
        assert cb.attempts == 1
        cb.record_attempt(success=False, error_signature="err")
        assert cb.attempts == 2

    def test_trips_after_max_retries(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.MAX_RETRIES):
            cb.record_attempt(success=False, error_signature="same")
        assert cb.is_tripped()
        assert cb.attempts == CircuitBreaker.MAX_RETRIES

    def test_different_error_resets_counter_to_one(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="error_a")
        cb.record_attempt(success=False, error_signature="error_a")
        assert cb.attempts == 2
        # Different error — progress detected
        cb.record_attempt(success=False, error_signature="error_b")
        assert cb.attempts == 1

    def test_empty_signature_does_not_trigger_reset(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="")
        cb.record_attempt(success=False, error_signature="")
        assert cb.attempts == 2

    def test_new_signature_after_empty_resets(self):
        cb = CircuitBreaker()
        cb.record_attempt(success=False, error_signature="")
        cb.record_attempt(success=False, error_signature="new_error")
        # "new_error" != "" so it resets to 1
        assert cb.attempts == 1


class TestTripping:
    def test_exactly_at_threshold(self):
        cb = CircuitBreaker()
        for i in range(CircuitBreaker.MAX_RETRIES - 1):
            cb.record_attempt(success=False, error_signature="e")
        assert not cb.is_tripped()
        cb.record_attempt(success=False, error_signature="e")
        assert cb.is_tripped()

    def test_stays_tripped_on_more_failures(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.MAX_RETRIES + 2):
            cb.record_attempt(success=False, error_signature="e")
        assert cb.is_tripped()

    def test_different_errors_prevent_tripping(self):
        cb = CircuitBreaker()
        # Each time a different error — counter resets to 1
        cb.record_attempt(success=False, error_signature="a")
        cb.record_attempt(success=False, error_signature="b")
        cb.record_attempt(success=False, error_signature="c")
        assert not cb.is_tripped()
        assert cb.attempts == 1


class TestReset:
    def test_reset_clears_failures(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.MAX_RETRIES):
            cb.record_attempt(success=False, error_signature="e")
        assert cb.is_tripped()
        cb.reset()
        assert not cb.is_tripped()
        assert cb.attempts == 0


class TestMaxRetries:
    def test_max_retries_is_three(self):
        assert CircuitBreaker.MAX_RETRIES == 3
