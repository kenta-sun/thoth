"""
本地命令行入口：不经过 MCP 直接调试记忆提取流水线。

用法：

    # 从文件读取原始文本
    uv run python -m thoth.main --file ./notes.md

    # 直接传入文本
    uv run python -m thoth.main --text "我上周搬到了大阪，现在主要用 Java 做后端开发。"

    # 从标准输入读取
    cat notes.md | uv run python -m thoth.main

    # 打开详细日志，观察每一步的判定过程
    uv run python -m thoth.main --file ./notes.md --verbose

输出约定：
- 结果报告与日志一律写到 **stderr**，stdout 保持干净。
  这样将来把同一套逻辑接到 MCP 的 stdio 传输上时，不会因为业务输出污染协议通讯。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from thoth.config import get_settings
from thoth.db.connection import DatabaseError, open_connection
from thoth.extraction.pipeline import ExtractionPipeline
from thoth.llm.client import LlmError

logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    """
    构造命令行参数解析器。

    返回：
    - 配置好的 ArgumentParser。``--file`` 与 ``--text`` 互斥，
      两者都不给时从标准输入读取。
    """
    parser = argparse.ArgumentParser(
        prog="thoth.main",
        description="从一段文本中提取长期记忆并写入数据库。",
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--file",
        type=Path,
        help="待提取的文本文件路径。",
    )
    source_group.add_argument(
        "--text",
        type=str,
        help="直接传入的待提取文本。",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出 DEBUG 级日志，可以看到每条记忆的分类与查重细节。",
    )

    return parser


def configure_logging(verbose: bool) -> None:
    """
    初始化日志。

    入参：
    - verbose : 为 True 时输出 DEBUG 级日志，否则只输出 INFO 及以上。

    说明：日志统一走 stderr，与结果报告的输出目标保持一致。
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        stream=sys.stderr,
    )

    # 这些第三方库在 DEBUG 级别下会打印每个请求的完整头部，把自己的日志彻底刷没，
    # 因此统一压到 WARNING。注意 openai 3.x 把 httpx / httpcore 内嵌成了
    # httpx2 / httpcore2，两套名字都要压。
    for noisy_logger in ("openai", "httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def resolve_input_text(args: argparse.Namespace) -> str:
    """
    根据命令行参数取得待提取的原始文本。

    入参：
    - args : 已解析的命令行参数。

    返回：
    - 原始文本内容。

    异常：
    - ValueError    ：文本为空白。
    - FileNotFoundError / OSError：文件不存在或读取失败。
    """
    if args.file is not None:
        text = args.file.read_text(encoding="utf-8")
        source = f"文件 {args.file}"
    elif args.text is not None:
        text = args.text
        source = "命令行参数"
    else:
        text = sys.stdin.read()
        source = "标准输入"

    if not text.strip():
        raise ValueError(f"{source}的内容为空，没有可提取的文本。")

    logger.info("已从%s读入 %d 个字符。", source, len(text))
    return text


def main(argv: list[str] | None = None) -> int:
    """
    命令行主流程。

    入参：
    - argv : 命令行参数列表。为 None 时使用 sys.argv。

    返回：
    - 进程退出码。0 表示成功，1 表示可预期的失败（配置错误、数据库不可用、模型调用失败等）。

    设计取舍：
    这里只捕获可预期的异常并转成友好的中文提示 + 退出码 1；
    未预期的异常故意不捕获，让堆栈完整暴露出来便于排查。
    """
    # 解析命令行参数（--file / --text / --verbose）。
    # argv 为 None 时，argparse 内部会自动使用 sys.argv[1:]。
    args = build_arg_parser().parse_args(argv)

    # 根据 --verbose 决定日志级别，并让日志统一输出到 stderr。
    # 必须在真正开始处理业务之前就配置好，否则前面的日志会用默认配置打印。
    configure_logging(args.verbose)

    try:
        # 拿到待提取的原始文本。
        # 内部会按优先级依次尝试 --file → --text → 标准输入，
        # 并在文本为空白时抛出 ValueError。
        text = resolve_input_text(args)

        # 加载全局配置（OpenAI/数据库/去重策略等），
        # get_settings 内部用 lru_cache 做单例，进程内多次调用只解析一次。
        settings = get_settings()

        # 打印一下本次运行实际使用的模型名，方便排查“为什么结果不对”时
        # 先确认调用的到底是哪个模型。
        logger.info(
            "使用对话模型 %s / Embedding 模型 %s。",
            settings.llm_model,
            settings.embedding_model,
        )

        # 打开数据库连接（with 语句保证函数退出时连接一定会被关闭/回收），
        # 然后用连接 + 配置组装出一条完整的提取流水线，
        # 最后对文本执行提取，得到包含“新增/重复放弃/待重拆”三类结果的报告。
        with open_connection(settings) as connection:
            pipeline = ExtractionPipeline.build(connection, settings)
            report = pipeline.run(text)

    except (OSError, ValueError) as exc:
        # 读文件失败（文件不存在/无权限）或者输入文本为空，都会落到这里。
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    except LlmError as exc:
        # 调用大模型（对话模型/Embedding 模型）失败，比如网络问题、API Key 无效等。
        print(f"大模型调用失败：{exc}", file=sys.stderr)
        return 1
    except DatabaseError as exc:
        # 数据库连接失败或者写入失败。
        print(f"数据库操作失败：{exc}", file=sys.stderr)
        return 1

    # 走到这里说明提取流程全部成功：先打印一个空行做分隔，
    # 再把提取报告（人类可读的文本形式）输出到 stderr。
    print("", file=sys.stderr)
    print(report.render_text(), file=sys.stderr)

    # 返回 0 表示进程正常结束。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
