"""Cliente Redis no-op usado quando KV_URL não está configurado.

Implementa os métodos usados pela API (get, set, pipeline) como operações
que não fazem nada — `get` retorna sempre None (cache miss), `set` é
silenciosamente ignorado e `pipeline` retorna um pipe cujo execute()
devolve uma lista de zeros.
"""

from __future__ import annotations

import asyncio


class _NoopPipeline:
    """Pipeline que aceita qualquer chamada encadeada e retorna lista de zeros."""

    def __init__(self, expected_results: int = 4) -> None:
        self._results: list[int] = [0] * expected_results
        self._counter = 1  # quantos comandos foram empilhados

    def _grow(self, n: int = 1) -> None:
        self._counter += n
        if self._counter > len(self._results):
            self._results.extend([0] * (self._counter - len(self._results)))

    def zremrangebyscore(self, *args, **kwargs) -> _NoopPipeline:
        self._grow()
        return self

    def zadd(self, *args, **kwargs) -> _NoopPipeline:
        self._grow()
        return self

    def zcard(self, *args, **kwargs) -> _NoopPipeline:
        self._grow()
        return self

    def expire(self, *args, **kwargs) -> _NoopPipeline:
        self._grow()
        return self

    async def execute(self) -> list[int]:
        # Retorna uma lista de zeros com o tamanho igual ao número de comandos
        # Isso garante que count = (await pipe.execute())[2] → 0 (limite nunca atingido)
        return self._results[: self._counter]


class NoopRedis:
    """Redis falso — get sempre cache-miss, set é descartado, pipeline é no-op."""

    async def get(self, key: str) -> None:  # noqa: ARG002
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        return True

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()
