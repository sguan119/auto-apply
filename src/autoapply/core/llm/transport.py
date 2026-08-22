"""Shared LLM transport: local CLI subprocess or OpenAI-compatible HTTP.

Search rerank and deliver form-fill both call `complete_prompt()` then parse
their own JSON schema. This module does not know about PageDecision or ranked.
"""

from __future__ import annotations

import os
import shlex
import subprocess

import httpx

from autoapply.core.config import LLMSettings

_VALID_TRANSPORTS = frozenset({"cli", "http"})


class LLMTransportError(Exception):
    """CLI or HTTP call failed. Callers wrap this in their own error type."""


def complete_prompt(prompt: str, settings: LLMSettings) -> str:
    """Return the model's raw text reply (JSON object, possibly fenced)."""
    kind = (settings.transport or "cli").strip().lower()
    if kind not in _VALID_TRANSPORTS:
        raise LLMTransportError(
            f"unknown [llm].transport {settings.transport!r}; use 'cli' or 'http'"
        )
    if kind == "http":
        return _complete_http(prompt, settings)
    return _complete_cli(prompt, settings)


def split_command(command: str) -> list[str]:
    """Split a config command string into argv (Windows keeps backslashes)."""
    return shlex.split(command, posix=(os.name != "nt"))


def _complete_cli(prompt: str, settings: LLMSettings) -> str:
    argv = split_command(settings.command.replace("{model}", settings.model))
    env = dict(os.environ)
    env["LLM_MODEL"] = settings.model
    if settings.api_key:
        env["LLM_API_KEY"] = settings.api_key
    if settings.base_url:
        env["LLM_BASE_URL"] = settings.base_url

    try:
        result = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMTransportError(
            f"LLM CLI 超时（{settings.timeout}s）：{settings.command!r}"
        ) from exc
    except OSError as exc:
        raise LLMTransportError(
            f"LLM CLI 启动失败：{settings.command!r}：{exc}"
        ) from exc

    if result.returncode != 0:
        raise LLMTransportError(
            f"LLM CLI 非零退出码 {result.returncode}：{settings.command!r}\n"
            f"stderr: {result.stderr.strip()}\nstdout: {result.stdout.strip()}"
        )
    stdout = result.stdout.strip()
    if not stdout:
        raise LLMTransportError(
            f"LLM CLI 输出为空：{settings.command!r}\nstderr: {result.stderr.strip()}"
        )
    return stdout


def _complete_http(prompt: str, settings: LLMSettings) -> str:
    if not (settings.api_key or "").strip():
        raise LLMTransportError(
            "HTTP LLM transport needs LLM_API_KEY in .env (copy .env.example)"
        )
    if not (settings.base_url or "").strip():
        raise LLMTransportError(
            "HTTP LLM transport needs [llm].base_url "
            "(e.g. https://api.deepseek.com or https://api.openai.com/v1)"
        )

    url = _chat_completions_url(settings.base_url.strip())
    payload = {
        "model": settings.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key.strip()}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.timeout,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.TimeoutException as exc:
        raise LLMTransportError(
            f"HTTP LLM timed out ({settings.timeout}s) calling {url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise LLMTransportError(
            f"HTTP LLM {exc.response.status_code} from {url}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMTransportError(f"HTTP LLM request failed: {exc}") from exc
    except ValueError as exc:
        raise LLMTransportError(f"HTTP LLM response was not JSON: {exc}") from exc

    text = _message_content(body)
    if not text:
        raise LLMTransportError("HTTP LLM returned an empty message")
    return text


def _chat_completions_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def _message_content(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""
