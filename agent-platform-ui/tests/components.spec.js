import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import BarChart from '@/components/BarChart.vue'
import ChunkPreview from '@/components/knowledge/ChunkPreview.vue'
import ChunkSettingsForm from '@/components/knowledge/ChunkSettingsForm.vue'
import NodeInspector from '@/components/NodeInspector.vue'
import NodePalette from '@/components/NodePalette.vue'
import KeyValueEditor from '@/components/fields/KeyValueEditor.vue'
import RowsEditor from '@/components/fields/RowsEditor.vue'
import StringListEditor from '@/components/fields/StringListEditor.vue'
import { NODE_TYPES, defaultConfig } from '@/graph/nodeMeta'

describe('BarChart', () => {
  it('renders one rect per point in the series', () => {
    const wrapper = mount(BarChart, {
      props: { series: [{ date: 'd1', count: 2 }, { date: 'd2', count: 4 }], unit: '会话' },
    })
    expect(wrapper.findAll('rect')).toHaveLength(2)
    expect(wrapper.findAll('.chart__label').map((node) => node.text())).toEqual(['d1', 'd2'])
    expect(wrapper.find('.chart__max').text()).toBe('4')
    expect(wrapper.find('.chart__unit').text()).toBe('会话')
  })

  it('omits the unit badge when no unit is given', () => {
    const wrapper = mount(BarChart, { props: { series: [] } })
    expect(wrapper.find('.chart__unit').exists()).toBe(false)
    expect(wrapper.findAll('rect')).toHaveLength(0)
  })

  it('colours the bars with the colour prop', () => {
    const wrapper = mount(BarChart, { props: { series: [{ date: 'd', count: 1 }], color: '#f56c6c' } })
    expect(wrapper.find('rect').attributes('fill')).toBe('#f56c6c')
  })
})

describe('NodePalette', () => {
  it('renders every node type', () => {
    const wrapper = mount(NodePalette)
    expect(wrapper.findAll('button')).toHaveLength(NODE_TYPES.length)
    expect(wrapper.text()).toContain('LLM')
    expect(wrapper.text()).toContain('条件分支')
  })

  it('emits add with the clicked node type', async () => {
    const wrapper = mount(NodePalette)
    await wrapper.findAll('button')[2].trigger('click')
    expect(wrapper.emitted('add')).toEqual([[NODE_TYPES[2].type]])
  })

  it('honours a custom type list', () => {
    const wrapper = mount(NodePalette, { props: { types: [{ type: 'llm', label: 'L', color: '#fff', summary: 's' }] } })
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})

describe('KeyValueEditor', () => {
  it('seeds one row per entry', () => {
    const wrapper = mount(KeyValueEditor, { props: { modelValue: { a: '1', b: '2' } } })
    expect(wrapper.findAllComponents({ name: 'ElInput' })).toHaveLength(4)
  })

  it('emits the object when a value is committed', async () => {
    const wrapper = mount(KeyValueEditor, { props: { modelValue: { a: '1' } } })
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    inputs[1].vm.$emit('update:modelValue', '9')
    inputs[1].vm.$emit('change', '9')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([{ a: '9' }])
  })

  it('adds an empty row that is skipped until it has a key', async () => {
    const wrapper = mount(KeyValueEditor, { props: { modelValue: {} } })
    await wrapper.findAll('button').at(-1).trigger('click')
    expect(wrapper.findAllComponents({ name: 'ElInput' })).toHaveLength(2)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('drops a row on delete', async () => {
    const wrapper = mount(KeyValueEditor, { props: { modelValue: { a: '1', b: '2' } } })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([{ b: '2' }])
  })
})

describe('StringListEditor', () => {
  it('seeds one row per item', () => {
    const wrapper = mount(StringListEditor, { props: { modelValue: ['a', 'b'] } })
    expect(wrapper.findAllComponents({ name: 'ElInput' })).toHaveLength(2)
  })

  it('emits the list on commit, filtering blanks', async () => {
    const wrapper = mount(StringListEditor, { props: { modelValue: ['a', ''] } })
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    inputs[0].vm.$emit('change', 'a')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([['a']])
  })

  it('appends a blank row without emitting', async () => {
    const wrapper = mount(StringListEditor, { props: { modelValue: ['a'] } })
    await wrapper.findAll('button').at(-1).trigger('click')
    expect(wrapper.findAllComponents({ name: 'ElInput' })).toHaveLength(2)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('removes a row', async () => {
    const wrapper = mount(StringListEditor, { props: { modelValue: ['a', 'b'] } })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([['b']])
  })
})

describe('RowsEditor', () => {
  const columns = [
    { key: 'name', label: '工具名', kind: 'text' },
    { key: 'args', label: '参数', kind: 'json' },
  ]

  it('seeds rows from the model and renders both column kinds', () => {
    const wrapper = mount(RowsEditor, { props: { modelValue: [{ name: 'search', args: { q: 'x' } }], columns } })
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    expect(inputs).toHaveLength(2)
    expect(inputs[0].props('modelValue')).toBe('search')
    expect(inputs[1].props('modelValue')).toBe('{"q":"x"}')
  })

  it('parses a json cell and emits the row', () => {
    const wrapper = mount(RowsEditor, { props: { modelValue: [{ name: 'a', args: {} }], columns } })
    const jsonInput = wrapper.findAllComponents({ name: 'ElInput' })[1]
    jsonInput.vm.$emit('update:modelValue', '{"k":1}')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([[{ name: 'a', args: { k: 1 } }]])
  })

  it('keeps the raw text without emitting while the json is invalid', async () => {
    const wrapper = mount(RowsEditor, { props: { modelValue: [{ name: 'a', args: {} }], columns } })
    const jsonInput = wrapper.findAllComponents({ name: 'ElInput' })[1]
    jsonInput.vm.$emit('update:modelValue', '{oops')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await nextTick()
    expect(jsonInput.props('modelValue')).toBe('{oops')
  })

  it('appends a row seeded from the column kinds', async () => {
    const wrapper = mount(RowsEditor, { props: { modelValue: [], columns } })
    await wrapper.findAll('button').at(-1).trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([[{ name: '', args: {} }]])
  })

  it('removes a row and re-seeds the json text', async () => {
    const wrapper = mount(RowsEditor, {
      props: { modelValue: [{ name: 'a', args: { k: 1 } }, { name: 'b', args: {} }], columns },
    })
    await wrapper.find('.rows__remove').trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([[{ name: 'b', args: {} }]])
  })

  it('renders boolean columns as switches and seeds them as false', async () => {
    const boolColumns = [
      { key: 'name', label: '工具名', kind: 'text' },
      { key: 'discover', label: '发现', kind: 'boolean' },
    ]
    const wrapper = mount(RowsEditor, {
      props: { modelValue: [{ name: 'a', discover: true }], columns: boolColumns },
    })
    const switches = wrapper.findAllComponents({ name: 'ElSwitch' })
    expect(switches).toHaveLength(1)
    expect(switches[0].props('modelValue')).toBe(true)

    await wrapper.findAll('button').at(-1).trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([
      [
        { name: 'a', discover: true },
        { name: '', discover: false },
      ],
    ])
  })
})

describe('NodeInspector', () => {
  it('shows an empty state with no selection', () => {
    const wrapper = mount(NodeInspector, { props: { node: null } })
    expect(wrapper.text()).toContain('未选中节点')
  })

  it('shows the node type, id and every field', () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'llm_1', type: 'llm', title: '模型', config: defaultConfig('llm') } } })
    expect(wrapper.text()).toContain('llm_1')
    expect(wrapper.text()).toContain('系统提示词')
    expect(wrapper.text()).toContain('temperature')
  })

  it('renders the agent tool pool and reflection fields', () => {
    const wrapper = mount(NodeInspector, {
      props: { node: { id: 'agent_1', type: 'agent', title: '智能体', config: defaultConfig('agent') } },
    })
    expect(wrapper.text()).toContain('工具池')
    expect(wrapper.text()).toContain('反思轮数')
    expect(wrapper.text()).toContain('流水线成员')
  })

  it('renders approval and subgraph configuration fields', () => {
    const approval = mount(NodeInspector, {
      props: { node: { id: 'approval_1', type: 'approval', title: '审批', config: defaultConfig('approval') } },
    })
    expect(approval.text()).toContain('审批问题')
    expect(approval.text()).toContain('默认动作')

    const subgraph = mount(NodeInspector, {
      props: {
        node: { id: 'subgraph_1', type: 'subgraph', title: '子图', config: defaultConfig('subgraph') },
        graphOptions: [{ value: 'app-1', label: '子图应用' }],
      },
    })
    expect(subgraph.text()).toContain('候选子图')
    expect(subgraph.text()).toContain('路由智能体')
    expect(subgraph.text()).toContain('子图应用')
  })

  it('emits update when the node title changes', () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'answer_1', type: 'answer', title: '回答', config: defaultConfig('answer') } } })
    const titleInput = wrapper.findAllComponents({ name: 'ElInput' }).find((input) => input.props('modelValue') === '回答')
    titleInput.vm.$emit('update:modelValue', '新名称')
    expect(wrapper.emitted('update').at(-1)[0]).toMatchObject({ id: 'answer_1', title: '新名称' })
  })

  it('emits update when a text field changes', () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'answer_1', type: 'answer', title: '回答', config: defaultConfig('answer') } } })
    const templateInput = wrapper.findAllComponents({ name: 'ElInput' }).find((input) => input.props('modelValue') === '{{ text }}')
    templateInput.vm.$emit('update:modelValue', '你好 {{ text }}')
    const payload = wrapper.emitted('update').at(-1)[0]
    expect(payload.config.template).toBe('你好 {{ text }}')
  })

  it('emits a plain config that can be structured-cloned downstream', () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'answer_1', type: 'answer', title: '回答', config: defaultConfig('answer') } } })
    const templateInput = wrapper.findAllComponents({ name: 'ElInput' }).find((input) => input.props('modelValue') === '{{ text }}')
    templateInput.vm.$emit('update:modelValue', '你好')
    const payload = wrapper.emitted('update').at(-1)[0]
    // 草稿是响应式代理，直接下发会让 GraphCanvas 的 structuredClone 抛 DataCloneError
    expect(() => structuredClone(payload.config)).not.toThrow()
  })

  it('emits remove with the node id', async () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'llm_1', type: 'llm', title: '', config: {} } } })
    const removeButton = wrapper.findAll('button').find((button) => button.text().includes('删除节点'))
    await removeButton.trigger('click')
    expect(wrapper.emitted('remove')).toEqual([['llm_1']])
  })

  it('renders the knowledge node dataset picker and retrieval overrides', () => {
    const wrapper = mount(NodeInspector, {
      props: {
        node: { id: 'knowledge_1', type: 'knowledge', title: '知识检索', config: defaultConfig('knowledge') },
        datasetOptions: [{ value: 'ds1', label: '政务库' }],
      },
    })
    expect(wrapper.text()).toContain('知识库')
    expect(wrapper.text()).toContain('粗召回 top_k')
    expect(wrapper.text()).toContain('混合检索')
  })

  it('renders the help hint for the end node outputs', () => {
    const wrapper = mount(NodeInspector, { props: { node: { id: 'end_1', type: 'end', title: '', config: { outputs: {} } } } })
    expect(wrapper.text()).toContain('值为裸表达式')
  })
})

describe('ChunkSettingsForm', () => {
  it('seeds defaults and emits a full config on change', async () => {
    const wrapper = mount(ChunkSettingsForm, { props: { modelValue: {} } })
    expect(wrapper.text()).toContain('分段标识符')

    const number = wrapper.findAllComponents({ name: 'ElInputNumber' })[0]
    number.vm.$emit('update:modelValue', 128)
    number.vm.$emit('change', 128)
    const config = wrapper.emitted('update:modelValue').at(-1)[0]
    expect(config.max_chars).toBe(128)
    expect(config.preprocess).toEqual({ replace_whitespace: true, remove_urls_emails: false })
    expect(config.qa_mode).toBe(false)
  })

  it('reflects a provided config', () => {
    const wrapper = mount(ChunkSettingsForm, {
      props: {
        modelValue: {
          max_chars: 300,
          qa_mode: true,
          preprocess: { replace_whitespace: false, remove_urls_emails: true },
        },
      },
    })
    expect(wrapper.findAllComponents({ name: 'ElInputNumber' })[0].props('modelValue')).toBe(300)
    expect(wrapper.text()).toContain('Q&A')
  })
})

describe('ChunkPreview', () => {
  it('shows the estimated chunk count and each chunk', () => {
    const wrapper = mount(ChunkPreview, {
      props: { chunks: [{ position: 0, content: '甲' }, { position: 1, content: '乙' }], total: 2 },
    })
    expect(wrapper.text()).toContain('2 预估块')
    expect(wrapper.findAll('.preview__item')).toHaveLength(2)
  })

  it('shows an empty hint when there are no chunks', () => {
    const wrapper = mount(ChunkPreview)
    expect(wrapper.text()).toContain('点击「预览块」查看分段结果')
  })
})
