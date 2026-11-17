import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import PdfToWordView from './PdfToWordView.vue'

vi.mock('./api', () => ({
  convertPdfToWord: vi.fn<typeof convertPdfToWord>(),
  PdfToWordApiError: class extends Error {},
}))

import { convertPdfToWord } from './api'

function createPdfFile(name = 'report.pdf', size = 100): File {
  const bytes = new Uint8Array(size)
  bytes[0] = 0x25
  bytes[1] = 0x50
  bytes[2] = 0x44
  bytes[3] = 0x46
  return new File([bytes], name, { type: 'application/pdf' })
}

function setFileInput(wrapper: ReturnType<typeof mount>, file: File) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', {
    value: file ? [file] : [],
    configurable: true,
  })
  return input
}

async function selectFile(wrapper: ReturnType<typeof mount>, file: File) {
  const input = setFileInput(wrapper, file)
  await input.dispatchEvent(new Event('change'))
}

describe('PdfToWordView', () => {
  beforeEach(() => {
    vi.mocked(convertPdfToWord).mockReset()
  })

  it('shows the upload prompt when no file is selected', () => {
    const wrapper = mount(PdfToWordView)
    expect(wrapper.text()).toContain('点击选择 PDF 文件')
    expect(wrapper.text()).toContain('开始转换')
    const button = wrapper.find('button.convert-button')
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('accepts a valid PDF file and enables conversion', async () => {
    const wrapper = mount(PdfToWordView)
    const input = setFileInput(wrapper, createPdfFile('report.pdf'))

    await input.dispatchEvent(new Event('change'))

    expect(wrapper.text()).toContain('report.pdf')
    const button = wrapper.find('button.convert-button')
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('wires the upload prompt to the native file input through a label', () => {
    const wrapper = mount(PdfToWordView)
    const prompt = wrapper.find('label.upload-prompt')

    expect(prompt.exists()).toBe(true)

    const input = prompt.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    expect(input.attributes('accept')).toContain('pdf')
  })

  it('shows the selected file name and formatted size', async () => {
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('report.pdf', 2048))

    expect(wrapper.text()).toContain('report.pdf')
    expect(wrapper.text()).toContain('2.0 KB')
  })

  it('accepts a PDF file dropped onto the upload zone', async () => {
    const wrapper = mount(PdfToWordView)
    await wrapper.find('.upload-zone').trigger('drop', {
      dataTransfer: { files: [createPdfFile('dropped.pdf')] },
    })

    expect(wrapper.text()).toContain('dropped.pdf')
    expect(wrapper.find('button.convert-button').attributes('disabled')).toBeUndefined()
  })

  it('allows selecting the same file again after clearing', async () => {
    const wrapper = mount(PdfToWordView)
    const file = createPdfFile('report.pdf')

    await selectFile(wrapper, file)
    expect(wrapper.text()).toContain('report.pdf')

    await wrapper.find('button.secondary-button').trigger('click')
    expect(wrapper.text()).toContain('点击选择 PDF 文件')

    await selectFile(wrapper, file)
    expect(wrapper.text()).toContain('report.pdf')
    expect(wrapper.find('button.convert-button').attributes('disabled')).toBeUndefined()
  })

  it('rejects non-PDF files', async () => {
    const wrapper = mount(PdfToWordView)
    const file = new File([new Uint8Array(10)], 'note.txt', { type: 'text/plain' })
    const input = setFileInput(wrapper, file)

    await input.dispatchEvent(new Event('change'))

    expect(wrapper.text()).toContain('仅支持 PDF 文件')
  })

  it('rejects files larger than 3 MB', async () => {
    const wrapper = mount(PdfToWordView)
    const input = setFileInput(wrapper, createPdfFile('big.pdf', 4 * 1024 * 1024))

    await input.dispatchEvent(new Event('change'))

    expect(wrapper.text()).toContain('文件过大')
  })

  it('rejects empty files', async () => {
    const wrapper = mount(PdfToWordView)
    const input = setFileInput(wrapper, createPdfFile('empty.pdf', 0))

    await input.dispatchEvent(new Event('change'))

    expect(wrapper.text()).toContain('文件为空')
  })

  it('shows converting state and disables the button during conversion', async () => {
    vi.mocked(convertPdfToWord).mockImplementation(
      () => new Promise(() => undefined),
    )
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())
    await wrapper.find('button.convert-button').trigger('click')

    expect(wrapper.text()).toContain('正在转换')
    expect(wrapper.find('button.convert-button').attributes('disabled')).toBeDefined()
  })

  it('shows the download link after successful conversion', async () => {
    const blob = new Blob(['docx-content'], { type: 'application/msword' })
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob,
      filename: 'report.docx',
      fontsNormalized: true,
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('report.pdf'))
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('转换完成')
    expect(wrapper.text()).toContain('下载 Word')
    expect(wrapper.text()).not.toContain('字体优化未成功')
    const link = wrapper.find('a.download-button')
    expect(link.attributes('download')).toBe('report.docx')
  })

  it('warns and still offers the download when font optimization failed', async () => {
    const blob = new Blob(['docx'])
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob,
      filename: 'report.docx',
      fontsNormalized: false,
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('report.pdf'))
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('字体优化未成功')
    expect(wrapper.text()).toContain(
      'Word 已生成，但自动字体优化未成功，部分文字可能显示异常。',
    )
    expect(wrapper.text()).toContain('手动调整字体')

    const link = wrapper.find('a.download-button')
    expect(link.exists()).toBe(true)
    expect(link.attributes('download')).toBe('report.docx')

    // Must not look like a plain success, and must not auto-download.
    expect(wrapper.find('.status-panel.success').classes()).toContain('is-degraded')
  })

  it('shows an error message when conversion fails', async () => {
    vi.mocked(convertPdfToWord).mockRejectedValue(
      Object.assign(new Error(), { message: '转换失败，请稍后重试。' }),
    )

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('转换失败')
  })

  it('allows clearing a selected file', async () => {
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('report.pdf'))
    expect(wrapper.text()).toContain('report.pdf')

    await wrapper.find('button.secondary-button').trigger('click')

    expect(wrapper.text()).toContain('点击选择 PDF 文件')
  })

  it('prevents duplicate submissions while converting', async () => {
    vi.mocked(convertPdfToWord).mockImplementation(
      () => new Promise(() => undefined),
    )
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())
    const button = wrapper.find('button.convert-button')

    await button.trigger('click')
    await button.trigger('click')

    expect(vi.mocked(convertPdfToWord)).toHaveBeenCalledTimes(1)
  })
})
