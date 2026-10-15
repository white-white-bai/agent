// 与 graph/schema.py 的 NodeType / CONFIG_MODELS 一一对应。

export const NODE_TYPES = [
  {
    type: 'start',
    label: '开始',
    color: '#67c23a',
    summary: '图入口，承载 inputs schema',
    fields: [],
    defaults: () => ({}),
  },
  {
    type: 'end',
    label: '结束',
    color: '#909399',
    summary: '图出口',
    fields: [
      { key: 'outputs', label: '输出变量', kind: 'keyvalue', help: '值为裸表达式，如 text、chunks[0].content' },
    ],
    defaults: () => ({ outputs: {} }),
  },
  {
    type: 'llm',
    label: 'LLM',
    color: '#409eff',
    summary: '大模型调用',
    fields: [
      { key: 'provider', label: '模型', kind: 'model-select', help: '来自 AP_LLM_MODELS 的模型条目；留空用清单第一个' },
      { key: 'system_prompt', label: '系统提示词', kind: 'textarea', rows: 3 },
      { key: 'user_prompt', label: '用户提示词', kind: 'textarea', rows: 4 },
      { key: 'temperature', label: 'temperature', kind: 'number', step: 0.1, min: 0, max: 2 },
      { key: 'max_tokens', label: 'max_tokens', kind: 'number', min: 1, nullable: true },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      provider: '',
      system_prompt: '',
      user_prompt: '{{ query }}',
      temperature: 0.7,
      max_tokens: null,
      output_var: 'text',
    }),
  },
  {
    type: 'knowledge',
    label: '知识检索',
    color: '#e6a23c',
    summary: '内置向量库或外接检索',
    fields: [
      { key: 'retriever', label: 'retriever', kind: 'select', options: ['builtin', 'light_rag', 'knowflow', 'knowledge_graph'] },
      { key: 'dataset_ids', label: '数据集', kind: 'stringlist' },
      { key: 'query', label: '检索问题', kind: 'textarea', rows: 2 },
      { key: 'top_k', label: 'top_k', kind: 'number', min: 1 },
      { key: 'score_threshold', label: 'score_threshold', kind: 'number', step: 0.01, nullable: true },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      retriever: 'builtin',
      dataset_ids: [],
      query: '{{ query }}',
      top_k: 5,
      score_threshold: null,
      output_var: 'chunks',
    }),
  },
  {
    type: 'condition',
    label: '条件分支',
    color: '#f56c6c',
    summary: '表达式驱动路由',
    fields: [
      { key: 'branches', label: '分支', kind: 'rows', columns: [
        { key: 'id', label: '分支 id', kind: 'text' },
        { key: 'expression', label: '表达式', kind: 'text' },
      ] },
      { key: 'fallback_id', label: '兜底分支 id', kind: 'text' },
    ],
    defaults: () => ({ branches: [{ id: 'branch_1', expression: 'true' }], fallback_id: 'false' }),
  },
  {
    type: 'code',
    label: '代码',
    color: '#8e44ad',
    summary: '受限 Python 沙箱',
    fields: [
      { key: 'code', label: '代码（须定义 main(**inputs)）', kind: 'textarea', rows: 8 },
      { key: 'inputs', label: '入参', kind: 'rows', columns: [
        { key: 'name', label: '参数名', kind: 'text' },
        { key: 'expression', label: '表达式', kind: 'text' },
      ] },
      { key: 'outputs', label: '出参名', kind: 'stringlist' },
      { key: 'timeout_ms', label: '超时（毫秒）', kind: 'number', min: 1 },
    ],
    defaults: () => ({ code: 'def main(**inputs):\n    return {}', inputs: [], outputs: [], timeout_ms: 3000 }),
  },
  {
    type: 'tool',
    label: '工具',
    color: '#00b8a9',
    summary: 'MCP 工具调用',
    fields: [
      { key: 'tools', label: '调用清单', kind: 'rows', columns: [
        { key: 'name', label: '工具名', kind: 'text' },
        { key: 'server', label: 'MCP Server', kind: 'text' },
        { key: 'args', label: '参数', kind: 'json' },
      ] },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({ tools: [], output_var: 'tool_result' }),
  },
  {
    type: 'aggregate',
    label: '变量聚合',
    color: '#2f86d6',
    summary: '多路变量汇总',
    fields: [
      { key: 'variables', label: '变量表达式', kind: 'stringlist' },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({ variables: [], output_var: 'aggregated' }),
  },
  {
    type: 'answer',
    label: '回答',
    color: '#1e9e6a',
    summary: '流式输出到前端',
    fields: [
      { key: 'template', label: '回答模板', kind: 'textarea', rows: 4 },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({ template: '{{ text }}', output_var: 'answer' }),
  },
  {
    type: 'parameter-extractor',
    label: '参数提取',
    color: '#b5673a',
    summary: 'LLM 结构化参数提取，输出按参数名平铺',
    fields: [
      { key: 'provider', label: '模型', kind: 'model-select', help: '来自 AP_LLM_MODELS 的模型条目；留空用清单第一个' },
      { key: 'query', label: '提取内容', kind: 'textarea', rows: 2 },
      { key: 'instruction', label: '提取指令', kind: 'textarea', rows: 3 },
      { key: 'parameters', label: '参数定义', kind: 'rows', columns: [
        { key: 'name', label: '参数名', kind: 'text' },
        { key: 'type', label: '类型', kind: 'text' },
        { key: 'description', label: '描述', kind: 'text' },
        { key: 'required', label: '必填', kind: 'text' },
        { key: 'options', label: '可选值', kind: 'json' },
      ] },
      { key: 'temperature', label: 'temperature', kind: 'number', step: 0.1, min: 0, max: 2 },
      { key: 'max_tokens', label: 'max_tokens', kind: 'number', min: 1, nullable: true },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      provider: '',
      query: '{{ query }}',
      instruction: '',
      parameters: [],
      temperature: 0.7,
      max_tokens: null,
      output_var: 'extracted',
    }),
  },
  {
    type: 'template-transform',
    label: '模板转换',
    color: '#9a6cb8',
    summary: '本地变量绑定 + Jinja2 模板渲染',
    fields: [
      { key: 'variables', label: '入参', kind: 'rows', columns: [
        { key: 'name', label: '参数名', kind: 'text' },
        { key: 'expression', label: '表达式', kind: 'text' },
      ] },
      { key: 'template', label: '模板', kind: 'textarea', rows: 6 },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({ variables: [], template: '', output_var: 'output' }),
  },
]

const BY_TYPE = new Map(NODE_TYPES.map((meta) => [meta.type, meta]))

export function nodeMeta(type) {
  return BY_TYPE.get(type) || { type, label: type, color: '#606266', summary: '', fields: [], defaults: () => ({}) }
}

export function defaultConfig(type) {
  const meta = nodeMeta(type)
  return structuredClone(meta.defaults())
}

export function createNode(type, id, position = { x: 0, y: 0 }) {
  return { id, type, title: nodeMeta(type).label, position, config: defaultConfig(type) }
}

export function conditionPorts(config) {
  const branches = Array.isArray(config && config.branches) ? config.branches : []
  const ports = branches.filter((branch) => branch && branch.id).map((branch) => branch.id)
  if (config && config.fallback_id && !ports.includes(config.fallback_id)) {
    ports.push(config.fallback_id)
  }
  return ports
}
