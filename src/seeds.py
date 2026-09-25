"""首次运行时生成的示例 Prompt。

只在 prompts/ 目录下一个 Markdown 文件都没有时写入，绝不会覆盖用户已有内容。
"""

from __future__ import annotations

from pathlib import Path

from .fsutil import atomic_write_text
from .prompt_store import PromptStore

SAMPLE_PROMPTS: dict[str, str] = {
    "Research/精读论文.md": (
        "精读本文：研究问题｜核心贡献｜方法/论证｜关键证据｜主要结论｜局限与疑点｜"
        "未解问题｜可延伸方向。按论文实际内容回答，不强行套模板；所有判断基于原文，"
        "不确定则注明。\n"
    ),
    "Research/寻找研究Gap.md": (
        "从研究者视角分析本文还没有解决的问题：局限、未验证假设、可放宽条件、"
        "缺失证据、可扩展场景及值得继续研究的方向。区分原文事实与推测。\n"
    ),
    "Research/最小复现.md": (
        "请为这个问题设计并实现一个最小复现：剥离无关依赖，只保留触发问题的必要代码与数据。\n\n"
        "请给出：\n"
        "1. 复现步骤（可直接照做）\n"
        "2. 期望行为与实际行为\n"
        "3. 关键代码与运行方式\n"
        "4. 如果无法复现，说明还缺少哪些信息\n"
    ),
    "Coding/Bug诊断.md": (
        "先复现并定位真实根因，不要立即修改代码。给出故障链路、根因、受影响范围"
        "和最小修复方案；确认后再修改。\n"
    ),
    "Coding/Code Review.md": (
        "请审查以上代码，按严重程度排序输出：\n\n"
        "正确性 → 边界条件 → 并发与资源释放 → 错误处理 → 可读性与命名 → 性能隐患 → 安全隐患。\n\n"
        "每条给出：问题、影响、具体的修改建议（尽量给最小补丁）。不确定的地方明确标注为推测。\n"
    ),
    "Coding/大步开发.md": (
        "先读取真实项目结构与现有实现，再直接完成本次功能。优先复用现有架构，"
        "避免无关重构。完成后进行真实运行验证，并简洁汇报修改内容、验证结果和剩余问题。\n"
    ),
    "Coding/项目诊断.md": (
        "请检查以下项目：\n\n"
        "{{PROJECT_PATH}}\n\n"
        "当前任务：\n\n"
        "{{TASK}}\n\n"
        "要求找出真实根因，不要只修表面问题。\n"
    ),
    "Writing/技术报告.md": (
        "请把以下内容整理成一份技术报告，结构为：\n\n"
        "背景与目标 → 现状与问题 → 方案与取舍 → 实施细节 → 验证结果 → 风险与遗留问题 → 后续计划。\n\n"
        "面向工程师读者，简洁准确，不夸大结论，数据与判断分开表述。\n"
    ),
}


def ensure_sample_prompts(store: PromptStore) -> int:
    """当 prompts/ 下没有任何 Markdown 时写入示例，返回写入数量。"""
    if not store.is_empty():
        return 0

    written = 0
    for relative, content in SAMPLE_PROMPTS.items():
        target = store.root / Path(relative)
        if target.exists():
            continue
        atomic_write_text(target, content, newline="\n")
        written += 1
    return written


__all__ = ["SAMPLE_PROMPTS", "ensure_sample_prompts"]
