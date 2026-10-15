"""内置图模板：编辑器可一键插入（当前为「政务咨询分角色流水线」）。"""
from __future__ import annotations

from typing import Any

from agent_platform.graph.schema import GraphDef


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
            "position": {"x": 440, "y": 200},
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
            "position": {"x": 660, "y": 200},
            "config": {
                "agent": "gov.generate",
                "query": "{{ query }}\n\n意图：{{ intent }}\n\n资料：{{ reference }}",
                "output_var": "draft",
            },
        },
        {
            "id": "compliance5",
            "type": "agent",
            "title": "④ 合规质检",
            "position": {"x": 880, "y": 200},
            "config": {
                "agent": "gov.compliance",
                "query": "用户问题：{{ query }}\n\n待审答复：{{ draft }}",
                "output_var": "review",
            },
        },
        {
            "id": "answer6",
            "type": "answer",
            "title": "答复",
            "position": {"x": 1100, "y": 200},
            "config": {"template": "{{ draft }}", "output_var": "answer"},
        },
        {"id": "end7", "type": "end", "title": "结束", "position": {"x": 1300, "y": 200}, "config": {}},
    ]
    edges = [
        {"id": "e_start_intent", "source": "start1", "target": "intent2", "source_handle": ""},
        {"id": "e_intent_retrieval", "source": "intent2", "target": "retrieval3", "source_handle": ""},
        {"id": "e_retrieval_generate", "source": "retrieval3", "target": "generate4", "source_handle": ""},
        {"id": "e_generate_compliance", "source": "generate4", "target": "compliance5", "source_handle": ""},
        {"id": "e_compliance_answer", "source": "compliance5", "target": "answer6", "source_handle": ""},
        {"id": "e_answer_end", "source": "answer6", "target": "end7", "source_handle": ""},
    ]
    return GraphDef.model_validate({"nodes": nodes, "edges": edges}).model_dump(mode="json")


GRAPH_TEMPLATES: dict[str, dict[str, Any]] = {
    "pipeline.gov_consult": {
        "name": "政务咨询分角色流水线",
        "description": "意图识别 → 知识检索 → 内容生成 → 合规质检 → 答复，四个智能体依次处理。",
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
