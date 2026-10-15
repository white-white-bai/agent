"""提示词组装：system 骨架 + 少样本示例 + CoT 拆解脚手架，以及推理段抽取。"""
from __future__ import annotations

import re

from agent_platform.engine.agents.registry import AgentSpec, PromptSpec

REASONING_PATTERN = re.compile(r"<reasoning>(.*?)</reasoning>", re.DOTALL | re.IGNORECASE)

COT_HINT = (
    "回答前请先在 <reasoning> 标签内拆解问题：识别意图、列出所需信息与推理步骤；"
    "然后在标签外给出最终答复。推理要精炼，不要复述题目。"
)


def build_system_prompt(spec: AgentSpec, template: PromptSpec | None = None) -> str:
    parts: list[str] = []
    base = spec.system_prompt or (template.system_prompt if template else "")
    if base:
        parts.append(base)
    if template is not None and template.examples:
        lines = ["参考示例："]
        for index, item in enumerate(template.examples, start=1):
            lines.append(f"示例 {index}")
            lines.append(f"输入：{item.get('input', '')}")
            lines.append(f"输出：{item.get('output', '')}")
        parts.append("\n".join(lines))
    if spec.cot:
        if template is not None and template.cot_hint:
            parts.append(template.cot_hint)
        parts.append(COT_HINT)
    return "\n\n".join(part for part in parts if part)


def split_reasoning(text: str) -> tuple[str, str]:
    """抽出 <reasoning> 段落，返回 (正文, 推理)；没有标签时原样返回正文。"""
    if not text:
        return "", ""
    found = REASONING_PATTERN.search(text)
    if not found:
        return text.strip(), ""
    answer = REASONING_PATTERN.sub("", text).strip()
    return (answer or text.strip()), found.group(1).strip()
