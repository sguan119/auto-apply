"""autoapply.cli.main —— typer 入口。

薄命令行入口层（CLAUDE.md「核心逻辑与界面分离」）：每个命令只做「解析参数 →
调 core 层函数 → 格式化打印结果」，真正的编排/存储/浏览器逻辑全在
`core.deliver.runner`/`core.storage.repository` 等模块里，这里不重复实现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import load_settings
from autoapply.core.contracts import DeliveryStatus, DeliveryTask, RunSummary
from autoapply.core.deliver.runner import run_delivery
from autoapply.core.llm.cli_client import CliLLMClient
from autoapply.core.questions.channel import AutoAnswerChannel
from autoapply.core.storage import repository
from autoapply.cli.terminal_channel import TerminalQuestionChannel

# Windows 上 stdout 被重定向/管道时默认走 cp1252，中文帮助文本经 rich 渲染会
# UnicodeEncodeError 崩溃；显式把 std 流切到 utf-8，交互终端本就走 unicode 控制台 API，不受影响。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

app = typer.Typer(help="全自动求职投递工具 —— 搜索职位 → 改写简历 → 自动投递")
console = Console()

# retry 命令没有独立的材料来源（决策五：材料路径本该由 DeliveryTask 显式携带，
# 但手动重投时调用方手上通常只有 platform/job_id），退回跟 runner 挂起恢复
# 同一套 spec 决策五「PDF 路径约定」兜底——见 core.deliver.runner 模块文档
# 「恢复态的材料从哪来」，两处逻辑刻意保持一致。
_ARTIFACTS_ROOT = Path("data") / "artifacts"


@app.callback()
def main() -> None:
    """deliver 命令组入口。

    显式声明 callback 让 typer 始终把 app 当作「命令组」处理——否则只有单个
    子命令时 typer 会退化成单命令模式，`deliver version` 会被当成多余参数报错。
    """


@app.command()
def version() -> None:
    """打印版本信息。"""
    typer.echo("deliver 0.1.0")


@app.command("run")
def run_cmd(
    tasks: Path = typer.Option(
        Path("tasks.example.json"),
        "--tasks",
        help="待投职位任务 JSON 文件路径（DeliveryTask[] schema，见 README「tasks.json 格式」）",
    ),
    auto: bool = typer.Option(
        False, "--auto", help="本次运行强制自动模式（覆盖 config.toml 的 deliver.mode）"
    ),
    manual: bool = typer.Option(
        False, "--manual", help="本次运行强制手动模式（覆盖 config.toml 的 deliver.mode）"
    ),
    headless: bool = typer.Option(
        True, "--headless/--headful", help="浏览器是否无头运行（调试时用 --headful 观察操作）"
    ),
) -> None:
    """跑一次投递 run：加载 tasks.json → 驱动状态机 → 打印 RunSummary（PRD 七/九）。"""
    settings = _resolve_settings(auto=auto, manual=manual, headless=headless)

    task_list = _load_tasks(tasks)
    if not task_list:
        typer.echo(f"任务文件 {tasks} 为空或不存在，没有职位可投；本次 run 只会处理挂起恢复队列。")

    llm_client = CliLLMClient(settings.llm)
    question_channel = _build_question_channel(settings)

    summary = run_delivery(
        task_list,
        settings=settings,
        question_channel=question_channel,
        llm_client=llm_client,
    )
    _print_summary(summary)


@app.command("answer")
def answer_cmd() -> None:
    """交互式补答全部挂起问题：列出 → 逐条输入 → 落库 + 回写 bio（决策七「答案到达后先回写 bio 再重投」）。"""
    pending = repository.pending_unanswered_questions()
    if not pending:
        typer.echo("没有待补答的挂起问题。")
        return

    bio_store = YamlBioStore()
    typer.echo(f"共有 {len(pending)} 个待补答问题：")
    for item in pending:
        page_hint = f"[{item.question.page}] " if item.question.page else ""
        typer.echo(f"\n[{item.job.company} - {item.job.title}] {page_hint}{item.question.question}")
        answer_text = typer.prompt(">")
        repository.record_answer(item.id, answer_text)
        if item.question.field_path:
            bio_store.write_path(item.question.field_path, answer_text, item.question.question)

    typer.echo("\n已回写全部答案；下次 `deliver run` 会优先重投已补答完的挂起职位。")


@app.command("retry")
def retry_cmd(
    platform: str = typer.Argument(..., help="职位平台，如 workday"),
    job_id: str = typer.Argument(..., help="职位在该平台内的 ID"),
    auto: bool = typer.Option(False, "--auto", help="本次重投强制自动模式"),
    manual: bool = typer.Option(False, "--manual", help="本次重投强制手动模式"),
    headless: bool = typer.Option(True, "--headless/--headful", help="浏览器是否无头运行"),
) -> None:
    """手动重投单个失败职位（决策八：失败默认不自动重试，留这个命令显式触发）。"""
    record = repository.get_delivery(platform, job_id)
    if record is None:
        typer.echo(f"没有找到投递记录：{platform}/{job_id}", err=True)
        raise typer.Exit(code=1)
    if record.status is DeliveryStatus.SUCCEEDED:
        typer.echo("该职位已经 SUCCEEDED——决策八「SUCCEEDED 永不再投」，拒绝重投。", err=True)
        raise typer.Exit(code=1)

    settings = _resolve_settings(auto=auto, manual=manual, headless=headless)

    # 材料路径见模块顶部 `_ARTIFACTS_ROOT` 的说明。
    artifacts_dir = _ARTIFACTS_ROOT / platform / job_id
    cover_letter_pdf = artifacts_dir / "cover_letter.pdf"
    task = DeliveryTask(
        job=record.job,
        resume_pdf=artifacts_dir / "resume.pdf",
        cover_letter_pdf=cover_letter_pdf if cover_letter_pdf.exists() else None,
    )

    llm_client = CliLLMClient(settings.llm)
    question_channel = _build_question_channel(settings)

    summary = run_delivery(
        [task],
        settings=settings,
        question_channel=question_channel,
        llm_client=llm_client,
        force_keys={(platform, job_id)},
    )
    _print_summary(summary)


@app.command("status")
def status_cmd() -> None:
    """打印投递记录 + 挂起问题清单表格。"""
    # repository 没有专门的「列出全部」函数（阶段 2 只按 key 精确查），这里
    # 用 get_delivered_job_keys() 拿到全部键，再逐个查详情——status 是低频
    # 诊断命令，这一轮额外查询的代价可以接受，不值得为它专门加一个 repository
    # 函数（阶段 8 允许扩的 repository 范围只限 runs 表两个函数）。
    keys = sorted(repository.get_delivered_job_keys())
    records = [repository.get_delivery(p, j) for p, j in keys]
    records = [r for r in records if r is not None]

    table = Table(title="投递记录")
    table.add_column("平台")
    table.add_column("职位")
    table.add_column("状态")
    table.add_column("原因")
    table.add_column("run_id")
    if not records:
        typer.echo("还没有任何投递记录。")
    else:
        for record in records:
            table.add_row(
                record.job.platform,
                f"{record.job.company} - {record.job.title}",
                record.status.value,
                record.failure_reason or "",
                record.run_id,
            )
        console.print(table)

    pending = repository.pending_unanswered_questions()
    if pending:
        q_table = Table(title="待补答挂起问题（`deliver answer` 补答）")
        q_table.add_column("职位")
        q_table.add_column("问题")
        for item in pending:
            q_table.add_row(f"{item.job.company} - {item.job.title}", item.question.question)
        console.print(q_table)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _resolve_settings(*, auto: bool, manual: bool, headless: bool):
    if auto and manual:
        typer.echo("错误：--auto 和 --manual 不能同时指定", err=True)
        raise typer.Exit(code=1)

    settings = load_settings()
    if auto:
        settings.deliver.mode = "auto"
    elif manual:
        settings.deliver.mode = "manual"
    settings.browser.headless = headless
    return settings


def _build_question_channel(settings):
    """自动模式没有真人在场应答问询（PRD 七），用 `AutoAnswerChannel`（默认
    策略是「答不上来」，遇阻直接挂起，决策六/七既有降级路径）；手动模式走
    终端交互。"""
    if settings.deliver.mode == "auto":
        return AutoAnswerChannel()
    return TerminalQuestionChannel()


def _load_tasks(path: Path) -> list[DeliveryTask]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [DeliveryTask.model_validate(item) for item in raw]


def _print_summary(summary: RunSummary) -> None:
    table = Table(title=f"RunSummary run_id={summary.run_id}")
    table.add_column("指标")
    table.add_column("数值")
    table.add_row("总数", str(summary.total))
    table.add_row("成功", str(summary.succeeded))
    table.add_row("失败", str(sum(summary.failed_by_reason.values())))
    table.add_row("挂起", str(len(summary.suspended)))
    console.print(table)

    if summary.failed_by_reason:
        reason_table = Table(title="失败原因分布")
        reason_table.add_column("原因")
        reason_table.add_column("次数")
        for reason, count in summary.failed_by_reason.items():
            reason_table.add_row(reason, str(count))
        console.print(reason_table)

    if summary.suspended:
        susp_table = Table(title="本次挂起的职位")
        susp_table.add_column("平台")
        susp_table.add_column("职位ID")
        susp_table.add_column("职位")
        for job in summary.suspended:
            susp_table.add_row(job.platform, job.job_id, f"{job.company} - {job.title}")
        console.print(susp_table)

    if summary.unanswered_questions:
        q_table = Table(title="待补答问题（`deliver answer` 补答后下次 run 自动重投）")
        q_table.add_column("职位")
        q_table.add_column("问题")
        for question in summary.unanswered_questions:
            q_table.add_row(f"{question.job.company} - {question.job.title}", question.question)
        console.print(q_table)


if __name__ == "__main__":
    app()
