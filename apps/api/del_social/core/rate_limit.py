"""Fixed-window failure counters in Redis (ADR 002)."""
import hashlib

from redis.asyncio import Redis

LOGIN_EMAIL_LIMIT = 10  # failed logins per email per window
LOGIN_IP_LIMIT = 30  # failed logins per IP per window
LOGIN_WINDOW_SECONDS = 15 * 60


def login_email_key(email: str) -> str:
    # Hashed so Redis never holds a list of email addresses
    return "rl:login:email:" + hashlib.sha256(email.encode()).hexdigest()


def login_ip_key(ip: str) -> str:
    return f"rl:login:ip:{ip}"


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def is_blocked(self, key: str, limit: int) -> bool:
        count = await self._redis.get(key)
        return count is not None and int(count) >= limit

    async def record(self, key: str, window_seconds: int) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)  # window starts at the first failure
            await pipe.execute()

    async def reset(self, key: str) -> None:
        await self._redis.delete(key)
