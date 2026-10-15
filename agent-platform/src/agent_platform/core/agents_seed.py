"""内置提示词模板 / 智能体 / 工具示例的幂等播种（按 code / name 判重，不覆盖已有配置）。"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Agent, PromptTemplate, Tool

logger = logging.getLogger(__name__)

BUILTIN_PROMPTS: list[dict[str, Any]] = [
    {
        "code": "fewshot.gov_intent",
        "label": "政务意图识别（少样本）",
        "system_prompt": "你是政务咨询意图识别助手：判断用户问题属于哪一类业务，并抽取关键要素。",
        "examples": [
            {"input": "我想问下营业执照怎么变更", "output": "业务类型：市场准入/营业执照变更；关键要素：变更营业执照"},
            {"input": "公积金怎么提取", "output": "业务类型：住房公积金/提取；关键要素：提取公积金"},
            {"input": "今天天气怎么样", "output": "业务类型：非政务咨询；关键要素：无"},
        ],
        "cot_hint": "先判断是否属于政务事项，再抽取办理事项与关键要素。",
    },
    {
        "code": "fewshot.gov_answer",
        "label": "政务答复（少样本·多步）",
        "system_prompt": "你是政务咨询答复助手：回答准确、简洁，优先引用办事指南与知识库资料。",
        "examples": [
            {
                "input": "企业开办需要哪些材料？",
                "output": "1）名称核准材料；2）法定代表人身份证明；3）住所使用证明。建议通过政务服务网在线提交。",
            },
            {
                "input": "社保断缴会影响落户吗？",
                "output": "会。多数城市要求连续缴纳社保满一定月数，断缴需重新计算；具体以当地实施细则为准。",
            },
        ],
        "cot_hint": "先确认办理事项与适用地区，再分步骤给出材料与渠道。",
    },
]

BUILTIN_AGENTS: list[dict[str, Any]] = [
    {
        "code": "gov.intent",
        "label": "意图识别",
        "role": "intent",
        "mode": "react",
        "system_prompt": "你是意图识别智能体：判断用户咨询属于哪一类政务事项，抽取办理事项、地区、时间等要素，输出一句话结论。",
        "prompt_template": "fewshot.gov_intent",
        "cot": True,
        "max_steps": 3,
        "temperature": 0.1,
    },
    {
        "code": "gov.retrieval",
        "label": "知识检索",
        "role": "retrieval",
        "mode": "deep_search",
        "system_prompt": "你是知识检索智能体：围绕政务事项做多轮检索，汇总要点并标注来源编号。",
        "max_steps": 3,
        "temperature": 0.2,
        "retriever": {"retriever": "builtin", "dataset_ids": [], "top_k": 5},
    },
    {
        "code": "gov.generate",
        "label": "内容生成",
        "role": "generate",
        "mode": "reflection",
        "system_prompt": "你是内容生成智能体：基于检索资料与意图结论，写出面向办事群众的完整答复（材料、流程、渠道、时限），语气亲和。",
        "prompt_template": "fewshot.gov_answer",
        "cot": True,
        "reflection_rounds": 1,
        "temperature": 0.3,
    },
    {
        "code": "gov.compliance",
        "label": "合规质检",
        "role": "compliance",
        "mode": "reflection",
        "system_prompt": (
            "你是合规质检智能体：检查答复是否存在越权承诺、虚假政策、敏感表述或缺失依据。"
            '输出 JSON：{"pass": true, "reason": "...", "suggestion": "..."}。'
        ),
        "cot": True,
        "reflection_rounds": 1,
        "temperature": 0.0,
    },
]

BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "gov.business.query",
        "label": "政务业务查询（示例·需替换端点）",
        "category": "query",
        "kind": "http",
        "http_method": "POST",
        "http_path": "/tools/gov.business.query",
        "params": [
            {"name": "keyword", "type": "string", "required": True, "description": "业务关键词"},
            {"name": "region", "type": "string", "required": False, "description": "地区编码"},
            {"name": "page", "type": "number", "required": False, "description": "页码"},
        ],
    },
    {
        "name": "gov.guide.search",
        "label": "办事指南检索（示例·需替换端点）",
        "category": "query",
        "kind": "http",
        "http_method": "POST",
        "http_path": "/tools/gov.guide.search",
        "params": [
            {"name": "item_name", "type": "string", "required": True, "description": "事项名称"},
            {"name": "region", "type": "string", "required": False, "description": "地区编码"},
        ],
    },
    {
        "name": "gov.form.validate",
        "label": "表单校验（示例·需替换端点）",
        "category": "validate",
        "kind": "http",
        "http_method": "POST",
        "http_path": "/tools/gov.form.validate",
        "params": [
            {"name": "form_data", "type": "object", "required": True, "description": "待校验表单数据"},
            {"name": "rules", "type": "array", "required": False, "description": "校验规则"},
        ],
    },
]


def seed() -> None:
    """幂等播种：已存在的（按 code / name）不动。"""
    with session_scope() as session:
        for item in BUILTIN_PROMPTS:
            if session.scalar(select(PromptTemplate).where(PromptTemplate.code == item["code"])) is None:
                session.add(PromptTemplate(uuid=uuid.uuid4().hex, tenant_code="", is_builtin=1, **item))
        for item in BUILTIN_AGENTS:
            if session.scalar(select(Agent).where(Agent.code == item["code"])) is None:
                data = {"tools": [], "pipeline": [], "retriever": {}, "prompt_template": "", "cot": False}
                data.update(item)
                session.add(Agent(uuid=uuid.uuid4().hex, tenant_code="", is_builtin=1, **data))
        for item in BUILTIN_TOOLS:
            if session.scalar(select(Tool).where(Tool.name == item["name"])) is None:
                data = {"server": "", "params": [], "fallback": {}}
                data.update(item)
                session.add(Tool(uuid=uuid.uuid4().hex, tenant_code="", is_builtin=1, **data))
