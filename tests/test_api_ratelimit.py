"""Testes do rate limiting (sliding window via Vercel KV / Upstash Redis).

Usa um FakeRedis em memória (mesma interface de `redis.asyncio.Redis` usada
pelo `check_and_increment`) para não depender de Redis real nem de settings.
"""

from __future__ import annotations

import asyncio

from api.core.ratelimit import (
    DEFAULT_PLAN,
    PLAN_LIMITS,
    check_and_increment,
    extract_client_id,
    get_plan_limits,
)

CLIENT_ID = "11111111-1111-1111-1111-111111111111"


class FakePipeline:
    """Pipeline Redis em memória que executa os comandos na ordem."""

    def __init__(self, store: dict[str, dict[str, float]]):
        self._store = store
        self._commands: list[tuple] = []

    def zremrangebyscore(self, key: str, min_: float, max_: float) -> FakePipeline:
        self._commands.append(("zremrangebyscore", key, min_, max_))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> FakePipeline:
        self._commands.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> FakePipeline:
        self._commands.append(("zcard", key))
        return self

    def expire(self, key: str, ttl: int) -> FakePipeline:
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self) -> list:
        results: list = []
        for command, *args in self._commands:
            if command == "zremrangebyscore":
                key, min_, max_ = args
                self._store[key] = {
                    member: score
                    for member, score in self._store.get(key, {}).items()
                    if not (min_ <= score <= max_)
                }
                results.append(None)
            elif command == "zadd":
                key, mapping = args
                self._store.setdefault(key, {}).update(mapping)
                results.append(len(mapping))
            elif command == "zcard":
                key = args[0]
                results.append(len(self._store.get(key, {})))
            elif command == "expire":
                results.append(True)
        return results


class FakeRedis:
    """Cliente Redis fake com pipeline em memória."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, float]] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store)


def run(coro) -> object:
    """Roda uma coroutine sem depender de pytest-asyncio."""
    return asyncio.run(coro)


def test_plan_limits_valores():
    assert PLAN_LIMITS["free"] == {"per_minute": 30, "per_day": 1_000}
    assert PLAN_LIMITS["pro"] == {"per_minute": 300, "per_day": 10_000}
    assert PLAN_LIMITS["enterprise"] == {"per_minute": 3_000, "per_day": 100_000}


def test_plan_limite_desconhecido_cai_em_free():
    assert get_plan_limits("gold") == PLAN_LIMITS[DEFAULT_PLAN]


def test_permite_ate_limite_por_minuto():
    redis = FakeRedis()
    for _ in range(30):
        result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0))
        assert result.allowed is True
    # 31º request estoura o limite de 30/min
    result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0))
    assert result.allowed is False
    assert result.limit == 30
    assert result.remaining == 0


def test_remaining_decresce():
    redis = FakeRedis()
    for i in range(10):
        result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0))
        assert result.remaining == 30 - (i + 1)


def test_janela_desliza_por_minuto():
    redis = FakeRedis()
    for _ in range(30):
        run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0))
    # 61s depois a janela de minuto deslizou e volta a permitir
    result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_061.0))
    assert result.allowed is True


def test_limite_diario_1000():
    redis = FakeRedis()
    # 1 request por minuto (61s de intervalo): a janela de minuto nunca estoura,
    # isolando a janela diária de 1000 requests.
    for i in range(1_000):
        result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0 + i * 61))
        assert result.allowed is True
    result = run(check_and_increment(redis, CLIENT_ID, "free", now=1_000.0 + 1_000 * 61))
    assert result.allowed is False
    assert result.reset_after == 86_400


def test_plano_pro_permite_300_por_minuto():
    redis = FakeRedis()
    for _ in range(300):
        result = run(check_and_increment(redis, CLIENT_ID, "pro", now=1_000.0))
        assert result.allowed is True
    result = run(check_and_increment(redis, CLIENT_ID, "pro", now=1_000.0))
    assert result.allowed is False


def test_extract_client_id_sem_authorization():
    assert extract_client_id(None) is None
    assert extract_client_id("") is None
    assert extract_client_id("Basic abc") is None
