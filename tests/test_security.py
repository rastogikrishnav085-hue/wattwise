import os

os.environ.setdefault("WATTWISE_ENV", "development")

from src.security import InMemoryRateLimiter


def test_is_blocked_does_not_record_a_hit():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    for _ in range(10):
        assert limiter.is_blocked("ip") is False   # checking must not consume the allowance
    assert limiter.allow("ip") and limiter.allow("ip")
    assert limiter.is_blocked("ip") is True
    assert limiter.allow("ip") is False
