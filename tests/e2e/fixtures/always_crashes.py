"""App that always crashes (exit 1).  Used to test the circuit breaker."""
import sys

print("Traceback (most recent call last):", file=sys.stderr)
print('  File "always_crashes.py", line 1, in <module>', file=sys.stderr)
print("RuntimeError: permanent failure", file=sys.stderr)
raise SystemExit(1)
