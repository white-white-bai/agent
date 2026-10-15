<script setup>
import { Graph } from '@antv/x6'
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { nextNodeId, nodeCell, portItems, readGraph, toCells, toDefinition } from '@/graph/mapper'
import { createNode, nodeMeta } from '@/graph/nodeMeta'

const props = defineProps({
  definition: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['select', 'change'])

const container = ref(null)
const graph = shallowRef(null)

let syncing = false
let placed = 0
let selectedEdge = null

// 悬浮在连线上时显示「×」删除按钮（X6 内置工具），点击即删边
const EDGE_REMOVE_TOOL = { name: 'button-remove', args: { distance: -32, offset: 0 } }

function paintEdge(edge, active) {
  edge.attr('line/stroke', active ? '#f56c6c' : '#a8abb2')
  edge.attr('line/strokeWidth', active ? 2.5 : 1.5)
}

function selectEdge(edge) {
  if (selectedEdge && selectedEdge !== edge) {
    paintEdge(selectedEdge, false)
  }
  selectedEdge = edge || null
  if (selectedEdge) {
    paintEdge(selectedEdge, true)
  }
}

function removeSelectedEdge() {
  if (!selectedEdge || !graph.value) {
    return false
  }
  const edge = selectedEdge
  selectedEdge = null
  graph.value.removeCell(edge)
  return true
}

function onKeydown(event) {
  if (event.key !== 'Delete' && event.key !== 'Backspace') {
    return
  }
  const target = event.target
  const tag = (target && target.tagName) || ''
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || (target && target.isContentEditable)) {
    return
  }
  if (removeSelectedEdge()) {
    event.preventDefault()
  }
}

function binding() {
  const instance = graph.value
  if (!instance) {
    return
  }
  instance.on('node:click', ({ node }) => {
    selectEdge(null)
    emit('select', payloadOf(node))
  })
  instance.on('blank:click', () => {
    selectEdge(null)
    emit('select', null)
  })
  instance.on('edge:click', ({ edge }) => {
    emit('select', null)
    selectEdge(edge)
  })
  instance.on('edge:mouseenter', ({ edge }) => {
    edge.removeTools()
    edge.addTools(EDGE_REMOVE_TOOL)
  })
  instance.on('edge:mouseleave', ({ edge }) => edge.removeTools())
  instance.on('node:added', notify)
  instance.on('node:removed', notify)
  instance.on('edge:added', notify)
  instance.on('edge:removed', () => {
    selectedEdge = null
    notify()
  })
  instance.on('edge:connected', notify)
  instance.on('cell:change:*', notify)
}

function notify() {
  if (!syncing) {
    emit('change')
  }
}

function payloadOf(node) {
  const data = node.getData() || {}
  const position = node.getPosition()
  return {
    id: node.id,
    type: data.type,
    title: data.title || '',
    position: { x: position.x, y: position.y },
    config: structuredClone(data.config || {}),
  }
}

function loadDefinition(definition) {
  const instance = graph.value
  if (!instance) {
    return
  }
  syncing = true
  selectedEdge = null
  instance.fromJSON(toCells(definition || {}))
  syncing = false
  placed = instance.getNodes().length
  if (instance.zoomToFit) {
    instance.zoomToFit({ maxScale: 1, padding: 24 })
  }
}

function addNode(type, position) {
  const instance = graph.value
  if (!instance) {
    return null
  }
  const offset = placed++ % 6
  const node = createNode(type, nextNodeId(type, instance.getNodes().map((cell) => cell.id)), position || {
    x: 40 + offset * 28,
    y: 40 + offset * 28,
  })
  syncing = true
  const cell = instance.addNode(nodeCell(node))
  syncing = false
  emit('change')
  emit('select', payloadOf(cell))
  return payloadOf(cell)
}

function applyNode(patch) {
  const instance = graph.value
  const cell = instance && instance.getCellById(patch.id)
  if (!cell) {
    return
  }
  const data = cell.getData() || {}
  const config = structuredClone(patch.config || {})
  syncing = true
  cell.setData({ ...data, title: patch.title || '', config })
  cell.attr('label/text', patch.title || nodeMeta(data.type).label)
  cell.setProp('ports/items', portItems({ type: data.type, config }))
  syncing = false
  emit('change')
}

function removeNode(id) {
  const instance = graph.value
  if (!instance) {
    return
  }
  syncing = true
  instance.removeCell(id)
  syncing = false
  emit('select', null)
  emit('change')
}

function readDefinition(base) {
  const instance = graph.value
  return toDefinition(instance ? readGraph(instance) : { nodes: [], edges: [] }, base)
}

function zoomToFit() {
  if (graph.value && graph.value.zoomToFit) {
    graph.value.zoomToFit({ maxScale: 1, padding: 24 })
  }
}

onMounted(async () => {
  await nextTick()
  graph.value = new Graph({
    container: container.value,
    grid: { size: 10, visible: true },
    panning: true,
    mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'] },
    connecting: {
      allowBlank: false,
      allowLoop: false,
      snap: true,
      highlight: true,
      connector: 'smooth',
      createEdge() {
        return graph.value.createEdge({
          attrs: { line: { stroke: '#a8abb2', strokeWidth: 1.5, targetMarker: { name: 'block', size: 7 } } },
        })
      },
    },
  })
  binding()
  loadDefinition(props.definition)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (graph.value) {
    graph.value.dispose()
    graph.value = null
  }
})

defineExpose({ loadDefinition, addNode, applyNode, removeNode, readDefinition, zoomToFit, payloadOf })
</script>

<template>
  <div ref="container" class="canvas" />
</template>

<style scoped>
.canvas {
  width: 100%;
  height: 100%;
  min-height: 520px;
  background: var(--el-fill-color-blank);
}
</style>
