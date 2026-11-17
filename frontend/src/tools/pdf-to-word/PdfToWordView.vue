<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import { pdfToWordTool } from '@/app/tools'
import ToolPageLayout from '@/shared/components/ToolPageLayout.vue'

import { convertPdfToWord, PdfToWordApiError } from './api'

type ConversionState = 'idle' | 'selected' | 'converting' | 'success' | 'error'

const MAX_FILE_SIZE = 3 * 1024 * 1024

const selectedFile = ref<File | null>(null)
const state = ref<ConversionState>('idle')
const errorMessage = ref('')
const downloadUrl = ref<string | null>(null)
const downloadFilename = ref('')
const fontsNormalized = ref(true)
const isDragging = ref(false)
let activeRequest: AbortController | null = null

const fileSizeLabel = computed(() => {
  if (!selectedFile.value) {
    return ''
  }
  return formatFileSize(selectedFile.value.size)
})

const canConvert = computed(() => !!selectedFile.value && state.value !== 'converting')

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function handleFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  input.value = ''
  applyFile(file)
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0] ?? null
  applyFile(file)
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  isDragging.value = true
}

function handleDragLeave(event: DragEvent) {
  event.preventDefault()
  isDragging.value = false
}

function applyFile(file: File | null) {
  resetResult()
  if (!file) {
    return
  }
  if (!isPdfFile(file)) {
    state.value = 'error'
    errorMessage.value = '仅支持 PDF 文件，请选择有效的 PDF 文档。'
    return
  }
  if (file.size > MAX_FILE_SIZE) {
    state.value = 'error'
    errorMessage.value = `文件过大（${formatFileSize(file.size)}），请上传小于 3 MB 的 PDF。`
    return
  }
  if (file.size === 0) {
    state.value = 'error'
    errorMessage.value = '上传的文件为空，请选择有效的 PDF 文档。'
    return
  }
  selectedFile.value = file
  state.value = 'selected'
  errorMessage.value = ''
}

function isPdfFile(file: File): boolean {
  const nameOk = file.name.toLowerCase().endsWith('.pdf')
  const typeOk = !file.type || file.type === 'application/pdf' || file.type === 'application/x-pdf'
  return nameOk && typeOk
}

function clearFile() {
  selectedFile.value = null
  state.value = 'idle'
  errorMessage.value = ''
  resetResult()
}

function resetResult() {
  if (downloadUrl.value) {
    URL.revokeObjectURL(downloadUrl.value)
    downloadUrl.value = null
  }
  downloadFilename.value = ''
  fontsNormalized.value = true
}

async function startConversion() {
  if (!selectedFile.value || state.value === 'converting') {
    return
  }
  activeRequest?.abort()
  const request = new AbortController()
  activeRequest = request
  state.value = 'converting'
  errorMessage.value = ''
  resetResult()

  try {
    const result = await convertPdfToWord(selectedFile.value, { signal: request.signal })
    if (request.signal.aborted) {
      return
    }
    downloadUrl.value = URL.createObjectURL(result.blob)
    downloadFilename.value = result.filename
    fontsNormalized.value = result.fontsNormalized
    state.value = 'success'
  } catch (error) {
    if (request.signal.aborted) {
      return
    }
    state.value = 'error'
    errorMessage.value =
      error instanceof PdfToWordApiError ? error.message : '转换失败，请稍后重试。'
  } finally {
    if (activeRequest === request) {
      activeRequest = null
    }
  }
}

onBeforeUnmount(() => {
  activeRequest?.abort()
  resetResult()
})
</script>

<template>
  <ToolPageLayout :title="pdfToWordTool.name" :description="pdfToWordTool.description">
    <div class="pdf-to-word-tool" :aria-busy="state === 'converting'">
      <section
        class="upload-zone"
        :class="{ 'is-dragging': isDragging, 'has-file': !!selectedFile }"
        @drop="handleDrop"
        @dragover="handleDragOver"
        @dragleave="handleDragLeave"
      >
        <label v-if="!selectedFile" class="upload-prompt">
          <span class="upload-icon" aria-hidden="true">⬆</span>
          <p class="upload-title">点击选择 PDF 文件</p>
          <p class="upload-hint">或将 PDF 拖拽到此处，最大支持 3 MB</p>
          <input
            type="file"
            accept="application/pdf,.pdf"
            class="file-input"
            @change="handleFileInput"
          />
        </label>
        <div v-else class="file-info">
          <div class="file-meta">
            <span class="file-name">{{ selectedFile.name }}</span>
            <span class="file-size">{{ fileSizeLabel }}</span>
          </div>
          <div class="file-actions">
            <button type="button" class="secondary-button" @click="clearFile">移除</button>
          </div>
        </div>
      </section>

      <div v-if="selectedFile" class="file-reselect">
        <label class="reselect-label">
          重新选择
          <input
            type="file"
            accept="application/pdf,.pdf"
            class="file-input-hidden"
            @change="handleFileInput"
          />
        </label>
      </div>

      <div class="action-row">
        <button
          type="button"
          class="convert-button"
          :disabled="!canConvert"
          @click="startConversion"
        >
          <template v-if="state === 'converting'">正在转换…</template>
          <template v-else>开始转换</template>
        </button>
      </div>

      <section v-if="state === 'converting'" class="status-panel converting" role="status">
        <div class="status-spinner" aria-hidden="true"></div>
        <p>正在处理 PDF，请稍候…</p>
      </section>

      <section
        v-else-if="state === 'success' && downloadUrl"
        class="status-panel success"
        :class="{ 'is-degraded': !fontsNormalized }"
      >
        <div class="status-body">
          <h2>{{ fontsNormalized ? '转换完成' : '转换完成，字体优化未成功' }}</h2>
          <p v-if="fontsNormalized">Word 文档已生成，可直接下载。</p>
          <p v-else class="status-warning">
            Word 已生成，但自动字体优化未成功，部分文字可能显示异常。你仍可下载文件，并在 Word
            或 WPS 中手动调整字体。
          </p>
        </div>
        <a :href="downloadUrl" :download="downloadFilename" class="download-button">
          下载 Word <span aria-hidden="true">↓</span>
        </a>
      </section>

      <section v-else-if="state === 'error'" class="status-panel error" role="alert">
        <h2>转换失败</h2>
        <p>{{ errorMessage }}</p>
        <button v-if="selectedFile" type="button" class="retry-button" @click="startConversion">
          重试
        </button>
      </section>

      <section class="guidance">
        <p class="guidance-title">使用说明</p>
        <ul>
          <li>支持普通文字型 PDF，扫描版暂不支持。</li>
          <li>复杂排版（多栏、艺术字）转换后可能存在差异。</li>
          <li>文件仅在转换期间临时处理，不会被保存。</li>
        </ul>
      </section>
    </div>
  </ToolPageLayout>
</template>

<style scoped>
.pdf-to-word-tool {
  display: grid;
  gap: var(--space-4);
}

.upload-zone {
  display: grid;
  align-content: center;
  justify-items: center;
  min-height: 12rem;
  border: 1px dashed var(--color-border-subtle);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  padding: var(--space-5);
  text-align: center;
  transition:
    border-color var(--transition-fast) ease,
    background var(--transition-fast) ease;
}

.upload-zone.is-dragging {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}

.upload-zone.has-file {
  border-style: solid;
}

.upload-prompt {
  display: grid;
  gap: var(--space-2);
  justify-items: center;
  width: 100%;
  cursor: pointer;
}

.upload-icon {
  display: grid;
  place-items: center;
  width: 3rem;
  height: 3rem;
  border: 1px solid var(--color-border-subtle);
  border-radius: 50%;
  color: var(--color-accent-active);
  font-size: 1.3rem;
  font-weight: 700;
}

.upload-title {
  color: var(--color-text-primary);
  font-weight: 700;
}

.upload-hint {
  color: var(--color-text-muted);
  font-size: var(--font-size-meta);
}

.file-input,
.file-input-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
}

.file-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
}

.file-meta {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  text-align: left;
}

.file-name {
  overflow: hidden;
  color: var(--color-text-primary);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  color: var(--color-text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: var(--font-size-meta);
}

button,
.download-button,
.reselect-label {
  min-height: var(--control-height);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  padding: 0.55rem 0.85rem;
  color: var(--color-text-primary);
  font-weight: 700;
  cursor: pointer;
}

button:hover:not(:disabled),
.download-button:hover,
.reselect-label:hover {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 8%, var(--color-surface));
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.secondary-button {
  color: var(--color-text-secondary);
}

.file-reselect {
  display: flex;
  justify-content: flex-start;
}

.reselect-label {
  display: inline-flex;
  align-items: center;
}

.action-row {
  display: flex;
  justify-content: flex-start;
}

.convert-button {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: var(--color-accent-contrast);
}

.convert-button:hover:not(:disabled) {
  border-color: var(--color-accent-hover);
  background: var(--color-accent-hover);
}

.status-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  border-radius: var(--radius-card);
  padding: var(--space-4);
}

.status-panel.converting {
  background: color-mix(in srgb, var(--color-accent) 4%, var(--color-surface));
  color: var(--color-text-secondary);
}

.status-panel.success {
  border: 1px solid color-mix(in srgb, var(--color-success) 25%, var(--color-border-subtle));
  background: color-mix(in srgb, var(--color-success) 5%, var(--color-surface));
}

.status-panel.error {
  border: 1px solid color-mix(in srgb, var(--color-danger) 25%, var(--color-border-subtle));
  background: color-mix(in srgb, var(--color-danger) 4%, var(--color-surface));
}

.status-panel h2 {
  color: var(--color-text-primary);
  font-size: 1.05rem;
  font-weight: 700;
}

.status-panel p {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.status-panel.success h2 {
  color: var(--color-success);
}

.status-panel.success.is-degraded {
  border-color: color-mix(in srgb, var(--color-danger) 25%, var(--color-border-subtle));
  background: color-mix(in srgb, var(--color-danger) 4%, var(--color-surface));
}

.status-panel.success.is-degraded h2 {
  color: var(--color-danger);
}

.status-warning {
  color: var(--color-text-secondary);
}

.status-panel.error h2 {
  color: var(--color-danger);
}

.status-body {
  display: grid;
  gap: var(--space-1);
}

.status-spinner {
  width: 1.1rem;
  height: 1.1rem;
  border: 2px solid var(--color-border-subtle);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.download-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border-color: var(--color-success);
  background: var(--color-success);
  color: var(--color-surface);
  text-decoration: none;
  white-space: nowrap;
}

.download-button:hover {
  background: color-mix(in srgb, var(--color-success) 85%, black);
}

.retry-button {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: var(--color-accent-contrast);
}

.retry-button:hover {
  border-color: var(--color-accent-hover);
  background: var(--color-accent-hover);
}

.guidance {
  border-top: 1px solid var(--color-border-subtle);
  padding-top: var(--space-4);
}

.guidance-title {
  margin-bottom: var(--space-2);
  color: var(--color-text-muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: var(--font-size-label);
  font-weight: 700;
  letter-spacing: 0.1em;
}

.guidance ul {
  display: grid;
  gap: var(--space-1);
  padding-left: 1.1rem;
  color: var(--color-text-secondary);
  font-size: 0.86rem;
  line-height: 1.5;
}

@media (max-width: 620px) {
  .file-info,
  .status-panel {
    align-items: flex-start;
    flex-direction: column;
  }

  .action-row .convert-button,
  .file-reselect .reselect-label {
    width: 100%;
    justify-content: center;
  }
}
</style>
