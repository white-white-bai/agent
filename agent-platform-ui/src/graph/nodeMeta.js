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
      { key: 'dataset_ids', label: '知识库', kind: 'dataset-select', help: '内置向量库检索的知识库（可多选）' },
      { key: 'query', label: '检索问题', kind: 'textarea', rows: 2 },
      { key: 'top_k', label: 'top_k', kind: 'number', min: 1 },
      { key: 'score_threshold', label: 'score_threshold', kind: 'number', step: 0.01, nullable: true },
      { key: 'coarse_top_k', label: '粗召回 top_k', kind: 'number', min: 1, nullable: true, help: '留空用全局检索配置' },
      { key: 'hybrid', label: '混合检索', kind: 'select', options: ['true', 'false'], nullable: true, help: '留空用全局开关' },
      { key: 'rerank', label: '重排序', kind: 'select', options: ['true', 'false'], nullable: true, help: '留空用全局开关' },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      retriever: 'builtin',
      dataset_ids: [],
      query: '{{ query }}',
      top_k: 5,
      score_threshold: null,
      coarse_top_k: null,
      hybrid: null,
      rerank: null,
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
  {
    type: 'http-request',
    label: 'HTTP 请求',
    color: '#0aa2c0',
    summary: '发 HTTP 请求，输出 body / status_code / headers',
    fields: [
      { key: 'method', label: '方法', kind: 'select', options: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'] },
      { key: 'url', label: 'URL', kind: 'text', placeholder: '支持 {{ 变量 }}' },
      { key: 'headers', label: '请求头', kind: 'keyvalue' },
      { key: 'params', label: 'Query 参数', kind: 'keyvalue' },
      { key: 'body_type', label: '请求体类型', kind: 'select', options: ['none', 'json', 'text'] },
      { key: 'body', label: '请求体', kind: 'textarea', rows: 4 },
      { key: 'timeout', label: '超时（秒）', kind: 'number', min: 1 },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      method: 'GET',
      url: '',
      headers: {},
      params: {},
      body_type: 'none',
      body: '',
      timeout: 30,
      output_var: 'http',
    }),
  },
  {
    type: 'question-classifier',
    label: '问题分类',
    color: '#d48806',
    summary: 'LLM 判定类别，类别 id 驱动分支',
    fields: [
      { key: 'provider', label: '模型', kind: 'model-select', help: '来自 AP_LLM_MODELS 的模型条目；留空用清单第一个' },
      { key: 'query', label: '待分类内容', kind: 'textarea', rows: 2 },
      { key: 'instruction', label: '分类指令', kind: 'textarea', rows: 3 },
      { key: 'classes', label: '类别（id 即分支句柄）', kind: 'rows', columns: [
        { key: 'id', label: '类别 id', kind: 'text' },
        { key: 'name', label: '类别名', kind: 'text' },
      ] },
      { key: 'temperature', label: 'temperature', kind: 'number', step: 0.1, min: 0, max: 2 },
      { key: 'max_tokens', label: 'max_tokens', kind: 'number', min: 1, nullable: true },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      provider: '',
      query: '{{ query }}',
      instruction: '',
      classes: [{ id: 'class_1', name: '类别一' }],
      temperature: 0,
      max_tokens: null,
      output_var: 'class_name',
    }),
  },
  {
    type: 'variable-assigner',
    label: '变量赋值',
    color: '#7a5af8',
    summary: '对表达式求值后写入同名变量',
    fields: [
      { key: 'items', label: '赋值项', kind: 'rows', columns: [
        { key: 'name', label: '变量名', kind: 'text' },
        { key: 'expression', label: '表达式', kind: 'text' },
      ] },
    ],
    defaults: () => ({ items: [] }),
  },
  {
    type: 'list-operator',
    label: '数组操作',
    color: '#c41d7f',
    summary: '取首/尾/下标/截取/筛选/排序/长度',
    fields: [
      { key: 'variable', label: '数组表达式', kind: 'text', placeholder: '如 knowledge_1 或 chunks' },
      { key: 'operation', label: '操作', kind: 'select', options: ['first', 'last', 'at', 'limit', 'filter', 'sort', 'size'] },
      { key: 'index', label: '下标（at）', kind: 'number' },
      { key: 'count', label: '数量（limit）', kind: 'number', min: 0 },
      { key: 'expression', label: '元素表达式（filter/sort）', kind: 'text', placeholder: '如 item > 3 或 item.score' },
      { key: 'desc', label: '降序（sort）', kind: 'boolean' },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      variable: '',
      operation: 'first',
      index: 0,
      count: 3,
      expression: '',
      desc: false,
      output_var: 'list_result',
    }),
  },
  {
    type: 'agent',
    label: '智能体',
    color: '#5a54f9',
    summary: '按角色与 9 种工作模式编排的多智能体节点',
    fields: [
      { key: 'agent', label: '智能体', kind: 'agent-select', help: '来自「智能体」页的定义' },
      {
        key: 'mode',
        label: '覆盖工作模式',
        kind: 'select',
        options: ['react', 'autonomous', 'plan_execute', 'reflection', 'supervisor', 'pipeline', 'agent_as_tool', 'deep_search'],
        help: '留空用智能体自身的模式；autonomous 走原生工具调用 + 消息栈',
      },
      { key: 'query', label: '输入', kind: 'textarea', rows: 3 },
      { key: 'tools', label: '工具池', kind: 'rows', columns: [
        { key: 'name', label: '工具名', kind: 'text' },
        { key: 'server', label: 'MCP Server', kind: 'text' },
        { key: 'discover', label: '发现', kind: 'boolean' },
        { key: 'args', label: '参数', kind: 'json' },
        { key: 'on_error', label: '失败策略', kind: 'text' },
      ], help: 'discover=true 时从该 server 的 MCP tools/list 发现工具（需开启 AP_TOOL_DISCOVERY_ENABLED）' },
      { key: 'pipeline', label: '流水线成员', kind: 'stringlist', help: 'pipeline / supervisor / agent_as_tool 使用' },
      { key: 'prompt_template', label: '少样本模板 code', kind: 'text' },
      { key: 'reflection_rounds', label: '反思轮数', kind: 'number', min: 0 },
      { key: 'cot', label: '思维链覆盖', kind: 'select', options: ['true', 'false'], help: '留空用智能体定义' },
      { key: 'max_steps', label: 'max_steps', kind: 'number', min: 1 },
      { key: 'temperature', label: 'temperature', kind: 'number', step: 0.1, min: 0, max: 2 },
      { key: 'max_tokens', label: 'max_tokens', kind: 'number', min: 1, nullable: true },
      { key: 'output_var', label: '输出变量', kind: 'text' },
    ],
    defaults: () => ({
      agent: '',
      mode: '',
      query: '{{ query }}',
      tools: [],
      pipeline: [],
      prompt_template: '',
      reflection_rounds: 2,
      cot: '',
      max_steps: 6,
      temperature: 0.3,
      max_tokens: null,
      output_var: 'agent_result',
    }),
  },
  {
    type: 'approval',
    label: '人工审批',
    color: '#d97706',
    summary: 'HITL 中断等待人工确认；关闭 HITL 时按默认动作自动通过',
    fields: [
      { key: 'question', label: '审批问题', kind: 'textarea', rows: 3 },
      { key: 'options', label: '可选动作', kind: 'stringlist' },
      { key: 'payload', label: '附加表达式', kind: 'text', help: '裸表达式，结果作为 interrupt 载荷' },
      { key: 'output_var', label: '输出变量', kind: 'text' },
      { key: 'default_action', label: '默认动作', kind: 'select', options: ['approve', 'reject'] },
    ],
    defaults: () => ({
      question: '请确认是否继续执行',
      options: ['approve', 'reject'],
      payload: '',
      output_var: 'approval',
      default_action: 'approve',
    }),
  },
  {
    type: 'subgraph',
    label: '子图',
    color: '#7c3aed',
    summary: '引用已发布图/模板，支持候选子图动态选择',
    fields: [
      { key: 'app_uuid', label: '子图应用', kind: 'graph-select', help: '留空时使用下方候选或模板' },
      { key: 'template_key', label: '模板 key', kind: 'text' },
      { key: 'version', label: '版本', kind: 'number', nullable: true, help: '留空用当前发布版' },
      {
        key: 'candidates',
        label: '候选子图',
        kind: 'rows',
        columns: [
          { key: 'label', label: '名称', kind: 'text' },
          { key: 'app_uuid', label: '应用 uuid', kind: 'text' },
          { key: 'template_key', label: '模板 key', kind: 'text' },
          { key: 'version', label: '版本', kind: 'text' },
        ],
      },
      { key: 'router', label: '路由智能体', kind: 'agent-select', help: '留空时用 state.route 或第一个候选' },
      { key: 'query', label: '输入', kind: 'textarea', rows: 3 },
      {
        key: 'inputs',
        label: '入参映射',
        kind: 'rows',
        columns: [
          { key: 'name', label: '参数名', kind: 'text' },
          { key: 'expression', label: '表达式', kind: 'text' },
        ],
      },
      { key: 'output_var', label: '输出变量', kind: 'text' },
      { key: 'max_depth', label: '最大嵌套深度', kind: 'number', min: 1 },
    ],
    defaults: () => ({
      app_uuid: '',
      template_key: '',
      version: null,
      candidates: [],
      router: '',
      query: '{{ query }}',
      inputs: [],
      output_var: 'subgraph_result',
      max_depth: 2,
    }),
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

export function classifierPorts(config) {
  const classes = Array.isArray(config && config.classes) ? config.classes : []
  return classes.filter((item) => item && item.id).map((item) => item.id)
}
