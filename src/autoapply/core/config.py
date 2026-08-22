"""autoapply.core.config —— 配置加载：config.toml（非密钥）+ .env/环境变量（密钥）→ Settings（spec 决策十）。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 仓库根目录约定：本文件位于 src/autoapply/core/config.py，向上三级即仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config.toml"
DEFAULT_EXAMPLE_CONFIG_PATH = _REPO_ROOT / "config.example.toml"
DEFAULT_ENV_PATH = _REPO_ROOT / ".env"


class DeliverSettings(BaseModel):
    """投递行为参数，对应 config.toml 的 [deliver] 段。"""

    mode: str = "manual"  # manual（默认，停在 READY_TO_SUBMIT 待确认）/ auto
    question_timeout: int = 1800  # WAITING_USER 超时秒数，超时转 SUSPENDED
    easy_apply_daily_limit: int = 50  # LinkedIn Easy Apply 滚动 24h 上限
    password_generation_mode: str = "random"  # random / template（阶段六 AUTHENTICATING 自动注册用）
    # template 模式的密码模板，"{rand}" 占位符会被替换成随机字母数字串（见
    # `core.deliver.auth.generate_password`）；不含占位符则原样使用固定密码
    # （不推荐，但不阻止——用户自己的选择）。
    password_template: str = "Deliver{rand}!2026"


class LLMSettings(BaseModel):
    """LLM 客户端配置，对应 config.toml 的 [llm] 段 + 环境变量密钥。

    决策十「LLM 可插拔」：`transport` 选择怎么调用模型。
    `cli`（默认）跑 `[llm].command` 子进程；`http` 打 OpenAI 兼容的
    Chat Completions（DeepSeek / OpenAI / Groq 等），密钥走 `LLM_API_KEY`。

    `command` 仅 `cli` 模式需要。`base_url` 在 `http` 模式是请求地址；
    在 `cli` 模式仍会透传给子进程环境变量 `LLM_BASE_URL`。

    ⚠️ CLI 的 stdout / HTTP 的 message content 必须是业务 JSON 原文
    （投递：PageDecision；搜索：ranked），不能是 Claude Code 信封。
    """

    transport: Literal["cli", "http"] = "cli"
    command: str = "claude -p"
    model: str = "claude-opus-4-8"
    base_url: str | None = None  # HTTP endpoint host; also passed to CLI as LLM_BASE_URL
    timeout: int = 60  # decide() 单次调用超时秒数，避免 CLI 子进程卡死拖垮整个 run
    api_key: str | None = None  # 来自环境变量 LLM_API_KEY，密钥不放 config.toml


class BrowserSettings(BaseModel):
    """Playwright 浏览器配置，对应 config.toml 的 [browser] 段（spec 决策三）。

    `user_data_dir` 是持久化 profile 目录，相对路径按仓库根解析；落在 `data/`
    下随 `data/` 一并被 `.gitignore` 排除（登录态/cookie 不能入仓库）。
    """

    headless: bool = True  # 无头运行；调试时可在 config.toml 里改 false 观察操作
    user_data_dir: str = "data/browser_profile"


class ImapSettings(BaseModel):
    """只读邮箱配置，对应 config.toml 的 [imap] 段 + 环境变量密钥（阶段六邮箱验证码取回）。"""

    host: str = "imap.gmail.com"
    port: int = 993
    username: str | None = None  # 环境变量 IMAP_USERNAME
    password: str | None = None  # 环境变量 IMAP_PASSWORD
    mailbox: str = "INBOX"  # 只读 SELECT/EXAMINE 的邮箱文件夹
    poll_interval: float = 5.0  # fetch_code/fetch_link 轮询间隔秒数
    poll_timeout: float = 120.0  # 轮询总超时秒数，超时返回 None（调用方降级处理）


class SearchSettings(BaseModel):
    """Search fetch/filter knobs, matching config.toml `[search]` (docs/search-spec.md §4.2)."""

    sites: list[str] = Field(
        default_factory=lambda: ["linkedin", "indeed", "glassdoor", "zip_recruiter"]
    )
    results_wanted: int = 100  # per site per keyword; rate-limit cap, not a relevance filter
    hours_old: int = 72
    score_threshold: float = 0.35  # Gate B; unused until the filter step
    shortlist_cap: int = 20
    llm_rerank: bool = True
    llm_timeout: int = 180  # one rerank call for the whole shortlist
    llm_model: str | None = None  # optional cheaper override of [llm].model
    llm_transport: Literal["cli", "http"] | None = None  # optional override of [llm].transport
    country_indeed: str = "USA"
    remote: bool = False  # bio `preferences.remote` overrides when set
    seen_lookback_hours: int = 168  # 7 days; skip keys already stored in search_seen


class CapsolverSettings(BaseModel):
    """CapSolver 打码服务配置，对应 config.toml 的 [capsolver] 段 + 环境变量密钥。

    `api_key` 是密钥（决策十，走环境变量 `CAPSOLVER_API_KEY`，不进 config.toml）；
    `base_url`/`poll_interval`/`poll_timeout` 是非密钥行为参数，可进 config.toml。
    """

    api_key: str | None = None  # 环境变量 CAPSOLVER_API_KEY
    base_url: str = "https://api.capsolver.com"
    poll_interval: float = 2.0  # getTaskResult 轮询间隔秒数
    poll_timeout: float = 120.0  # 求解总超时秒数，超时 → CaptchaSolveError


class Settings(BaseModel):
    """合并后的全局配置：config.toml 行为参数 + .env/环境变量密钥。"""

    deliver: DeliverSettings = Field(default_factory=DeliverSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    imap: ImapSettings = Field(default_factory=ImapSettings)
    capsolver: CapsolverSettings = Field(default_factory=CapsolverSettings)


def load_settings(
    config_path: str | Path | None = None,
    env_path: str | Path | None = None,
) -> Settings:
    """加载并合并配置：config.toml(tomllib) + .env(python-dotenv) → 校验后的 Settings。

    - `config_path` 缺省时优先用仓库根的 `config.toml`；不存在则退回 `config.example.toml`，
      保证还没做本地配置时也能跑通。
    - `env_path` 缺省时尝试加载仓库根的 `.env`；文件不存在也不报错，直接退回读取真实的
      进程环境变量（`.env` 只是本地开发的便利手段）。
    - 任何一段（[deliver]/[search]/[llm]/[imap]）在 config.toml 里缺失都不报错，用 Settings 默认值兜底。
    """
    resolved_config_path = _resolve_config_path(config_path)
    raw_config: dict = {}
    if resolved_config_path is not None and resolved_config_path.exists():
        with open(resolved_config_path, "rb") as f:
            raw_config = tomllib.load(f)

    resolved_env_path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
    # override=False：已存在的真实环境变量优先于 .env 文件内容
    load_dotenv(dotenv_path=resolved_env_path, override=False)

    llm_section = dict(raw_config.get("llm", {}))
    llm_section.setdefault("api_key", os.environ.get("LLM_API_KEY"))

    imap_section = dict(raw_config.get("imap", {}))
    imap_section.setdefault("username", os.environ.get("IMAP_USERNAME"))
    imap_section.setdefault("password", os.environ.get("IMAP_PASSWORD"))

    capsolver_section = dict(raw_config.get("capsolver", {}))
    capsolver_section["api_key"] = os.environ.get("CAPSOLVER_API_KEY")

    return Settings(
        deliver=raw_config.get("deliver", {}),
        search=raw_config.get("search", {}),
        llm=llm_section,
        browser=raw_config.get("browser", {}),
        imap=imap_section,
        capsolver=capsolver_section,
    )


def _resolve_config_path(config_path: str | Path | None) -> Path | None:
    if config_path is not None:
        return Path(config_path)
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    if DEFAULT_EXAMPLE_CONFIG_PATH.exists():
        return DEFAULT_EXAMPLE_CONFIG_PATH
    return None
