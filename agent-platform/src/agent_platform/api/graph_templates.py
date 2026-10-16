"""内置图模板：编辑器可一键插入（当前为「政务咨询分角色流水线」）。"""
from __future__ import annotations

from typing import Any

from agent_platform.graph.schema import GraphDef

MAX_COMPLIANCE_RETRIES = 2

# 合规打回的判定：优先认「判定：不通过」这一行，其次兼容 JSON 里的 "pass": false
REVISE_EXPRESSION = (
    "(('判定：不通过' in (review | default(''))) or "
    "('pass:false' in (review | default('') | lower | replace(' ', '') | replace('\"', '') | replace(\"'\", '')))) "
    f"and ((retry | default(0) | int) < {MAX_COMPLIANCE_RETRIES})"
)

GENERATE_QUERY = """{{ query }}

意图结论：{{ intent }}

检索资料：{{ reference }}{% if (review | default('')) %}

上一版答复被合规质检打回，意见如下：
{{ review }}

请据此重新生成答复，避免同样的问题。{% endif %}"""

ANSWER_TEMPLATE = (
    "{{ draft }}"
    "{% if (retry | default(0) | int) > 0 %}\n\n（已按合规意见修订 {{ retry }} 轮）{% endif %}"
)


def _pipeline_graph() -> dict[str, Any]:
    nodes = [
        {"id": "start1", "type": "start", "title": "开始", "position": {"x": 40, "y": 200}, "config": {}},
        {
            "id": "intent2",
            "type": "agent",
            "title": "① 意图识别",
            "position": {"x": 220, "y": 200},
            "config": {"agent": "gov.intent", "query": "{{ query }}", "output_var": "intent"},
        },
        {
            "id": "retrieval3",
            "type": "agent",
            "title": "② 知识检索",
            "position": {"x": 420, "y": 200},
            "config": {
                "agent": "gov.retrieval",
                "query": "{{ query }}\n\n意图结论：{{ intent }}",
                "output_var": "reference",
            },
        },
        {
            "id": "generate4",
            "type": "agent",
            "title": "③ 内容生成",
            "position": {"x": 620, "y": 200},
            "config": {"agent": "gov.generate", "query": GENERATE_QUERY, "output_var": "draft"},
        },
        {
            "id": "compliance5",
            "type": "agent",
            "title": "④ 合规质检",
            "position": {"x": 820, "y": 200},
            "config": {
                "agent": "gov.compliance",
                "query": "用户问题：{{ query }}\n\n待审答复：{{ draft }}",
                "output_var": "review",
            },
        },
        {
            "id": "cond6",
            "type": "condition",
            "title": "合规判定",
            "position": {"x": 1020, "y": 200},
            "config": {
                "branches": [{"id": "revise", "expression": REVISE_EXPRESSION}],
                "fallback_id": "pass",
            },
        },
        {
            "id": "revise7",
            "type": "variable-assigner",
            "title": "重写计数",
            "position": {"x": 900, "y": 400},
            "config": {"items": [{"name": "retry", "expression": "(retry | default(0) | int) + 1"}]},
        },
        {
            "id": "answer8",
            "type": "answer",
            "title": "答复",
            "position": {"x": 1240, "y": 160},
            "config": {"template": ANSWER_TEMPLATE, "output_var": "answer"},
        },
        {"id": "end9", "type": "end", "title": "结束", "position": {"x": 1440, "y": 160}, "config": {}},
    ]
    edges = [
        {"id": "e1", "source": "start1", "target": "intent2", "source_handle": ""},
        {"id": "e2", "source": "intent2", "target": "retrieval3", "source_handle": ""},
        {"id": "e3", "source": "retrieval3", "target": "generate4", "source_handle": ""},
        {"id": "e4", "source": "generate4", "target": "compliance5", "source_handle": ""},
        {"id": "e5", "source": "compliance5", "target": "cond6", "source_handle": ""},
        {"id": "e6", "source": "cond6", "target": "answer8", "source_handle": "pass"},
        {"id": "e7", "source": "cond6", "target": "revise7", "source_handle": "revise"},
        # 回环：打回则计数 +1 后重写；计数到上限走 pass 分支兜底
        {"id": "e8", "source": "revise7", "target": "generate4", "source_handle": ""},
        {"id": "e9", "source": "answer8", "target": "end9", "source_handle": ""},
    ]
    return GraphDef.model_validate({"nodes": nodes, "edges": edges}).model_dump(mode="json")


GRAPH_TEMPLATES: dict[str, dict[str, Any]] = {
    "pipeline.gov_consult": {
        "name": "政务咨询分角色流水线",
        "description": (
            "意图识别 → 知识检索 → 内容生成 → 合规质检 → 答复；合规判定不通过时回到内容生成重写，"
            f"最多重写 {MAX_COMPLIANCE_RETRIES} 轮（计数器兜底，不会死循环）。"
        ),
        "nodes": ["gov.intent", "gov.retrieval", "gov.generate", "gov.compliance"],
        "definition": _pipeline_graph(),
    }
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {"key": key, "name": item["name"], "description": item["description"], "nodes": item["nodes"]}
        for key, item in GRAPH_TEMPLATES.items()
    ]


def get_template(key: str) -> dict[str, Any] | None:
    return GRAPH_TEMPLATES.get(key)
