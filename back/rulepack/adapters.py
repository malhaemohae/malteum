from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import jsonschema


class AdapterError(RuntimeError):
    pass


class CandidateExtractor(Protocol):
    model: str

    def extract(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DeterministicRuleAdapter:
    model: str = "fake-deterministic-v1"

    def extract(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        del schema
        return json.loads(prompt)["candidate"]


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    endpoint: str
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    max_attempts: int = 3
    timeout_seconds: float = 30.0

    def extract(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self.max_attempts < 1:
            raise AdapterError("max_attempts는 1 이상이어야 함")
        key = os.environ.get(self.api_key_env)
        if not key:
            raise AdapterError(f"환경변수 {self.api_key_env}가 필요함")
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "candidate", "strict": True, "schema": schema},
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                choices = payload.get("choices") if isinstance(payload, dict) else None
                if not isinstance(choices, list) or not choices:
                    raise AdapterError("응답 choices가 비어 있거나 배열이 아님")
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    raise AdapterError("응답 content가 문자열이 아님")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise AdapterError("구조화 응답 최상위가 객체가 아님")
                return parsed
            except (
                AdapterError,
                TimeoutError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                urllib.error.URLError,
            ) as exc:
                last_error = exc
                status = getattr(exc, "code", None)
                if attempt + 1 >= self.max_attempts or status not in (
                    None,
                    429,
                    500,
                    502,
                    503,
                    504,
                ):
                    break
                time.sleep(0.25 * (2**attempt))
        raise AdapterError(f"구조화 후보 추출 실패: {type(last_error).__name__}") from last_error


def extract_batch(
    adapter: CandidateExtractor,
    requests: list[tuple[str, str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """후보별 오류를 격리해 한 실패가 나머지 배치를 중단하지 않게 함."""
    successes: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for item_id, prompt, schema in requests:
        try:
            candidate = adapter.extract(prompt, schema)
            jsonschema.validate(instance=candidate, schema=schema)
            if candidate["code"] != item_id:
                raise AdapterError("응답 code가 요청 항목과 다름")
            successes[item_id] = candidate
        except (AdapterError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            failures[item_id] = f"{type(exc).__name__}: {exc}"
    return successes, failures
