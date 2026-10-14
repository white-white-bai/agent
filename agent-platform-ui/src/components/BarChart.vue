<script setup>
import { computed } from 'vue'

import { barLayout, normalizeSeries, seriesMax } from '@/utils/chart'

const props = defineProps({
  series: { type: Array, default: () => [] },
  height: { type: Number, default: 160 },
  color: { type: String, default: '#409eff' },
  unit: { type: String, default: '' },
})

const items = computed(() => normalizeSeries(props.series))
const bars = computed(() => barLayout(items.value, { height: props.height }))
const max = computed(() => seriesMax(items.value))
</script>

<template>
  <div class="chart">
    <div class="chart__head">
      <span class="chart__max">{{ max }}</span>
      <span v-if="unit" class="chart__unit">{{ unit }}</span>
    </div>
    <svg class="chart__svg" :viewBox="`0 0 640 ${height}`" preserveAspectRatio="none" role="img">
      <rect v-for="(bar, index) in bars" :key="index" :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height" :fill="color" rx="2" />
    </svg>
    <div class="chart__axis">
      <span v-for="(bar, index) in bars" :key="index" class="chart__label">{{ bar.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
}

.chart__head {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 4px;
}

.chart__max {
  font-size: 18px;
  font-weight: 600;
}

.chart__unit {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.chart__svg {
  width: 100%;
  display: block;
  background: var(--el-fill-color-light);
}

.chart__axis {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.chart__label {
  flex: 1;
  text-align: center;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  white-space: nowrap;
}
</style>
