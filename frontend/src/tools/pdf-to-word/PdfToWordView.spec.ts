import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

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
  it.each(['remove', 'select', 'drop', 'invalid', 'cancel'])(
    'invalidates the pending request after %s',
    async (action) => {
      let resolve!: (value: Awaited<ReturnType<typeof convertPdfToWord>>) => void
      vi.mocked(convertPdfToWord).mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done
          }),
      )
      const wrapper = mount(PdfToWordView)
      await selectFile(wrapper, createPdfFile('old.pdf'))
      await wrapper.find('button.convert-button').trigger('click')
      const signal = vi.mocked(convertPdfToWord).mock.calls[0]?.[1]?.signal

      if (action === 'remove') {
        await wrapper.find('button.secondary-button').trigger('click')
      } else if (action === 'drop') {
        await wrapper.find('.upload-zone').trigger('drop', {
          dataTransfer: { files: [createPdfFile('new.pdf')] },
        })
      } else if (action === 'cancel') {
        const input = wrapper.find('input[type="file"]').element as HTMLInputElement
        Object.defineProperty(input, 'files', { value: [], configurable: true })
        input.dispatchEvent(new Event('change'))
      } else {
        const file =
          action === 'invalid'
            ? new File(['invalid'], 'bad.txt', { type: 'text/plain' })
            : createPdfFile('new.pdf')
        await selectFile(wrapper, file)
      }

      expect(signal?.aborted).toBe(true)
      resolve({
        blob: new Blob(['old']),
        filename: 'old.docx',
        fontsNormalized: true,
        ocrStatus: 'disabled',
      })
      await flushPromises()
      expect(wrapper.find('a.download-button').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('old.pdf')
      expect(wrapper.find('button.retry-button').exists()).toBe(false)
      expect(wrapper.find('button.convert-button').attributes('disabled') !== undefined).toBe(
        ['remove', 'invalid', 'cancel'].includes(action),
      )
      wrapper.unmount()
    },
  )

  it('keeps the new download when an older request resolves later', async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof convertPdfToWord>>) => void
    vi.mocked(convertPdfToWord)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve
          }),
      )
      .mockResolvedValueOnce({
        blob: new Blob(['new']),
        filename: 'new.docx',
        fontsNormalized: true,
        ocrStatus: 'applied',
      })
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('old.pdf'))
    await wrapper.find('button.convert-button').trigger('click')
    await selectFile(wrapper, createPdfFile('new.pdf'))
    await wrapper.find('button.convert-button').trigger('click')
    await flushPromises()
    resolveOld({
      blob: new Blob(['old']),
      filename: 'old.docx',
      fontsNormalized: true,
      ocrStatus: 'disabled',
    })
    await flushPromises()
    expect(wrapper.find('a.download-button').attributes('download')).toBe('new.docx')
    expect(wrapper.text()).toContain('new.pdf')
    wrapper.unmount()
  })

  it('aborts on unmount and ignores a late response', async () => {
    let resolve!: (value: Awaited<ReturnType<typeof convertPdfToWord>>) => void
    vi.mocked(convertPdfToWord).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())
    await wrapper.find('button.convert-button').trigger('click')
    const signal = vi.mocked(convertPdfToWord).mock.calls[0]?.[1]?.signal
    const createUrl = vi.spyOn(URL, 'createObjectURL')
    createUrl.mockClear()
    wrapper.unmount()
    resolve({
      blob: new Blob(['old']),
      filename: 'old.docx',
      fontsNormalized: true,
      ocrStatus: 'disabled',
    })
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(createUrl).not.toHaveBeenCalled()
    createUrl.mockRestore()
  })

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
    vi.mocked(convertPdfToWord).mockImplementation(() => new Promise(() => undefined))
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
      ocrStatus: 'disabled',
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
      ocrStatus: 'disabled',
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('report.pdf'))
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('字体优化未成功')
    expect(wrapper.text()).toContain('Word 已生成，但自动字体优化未成功，部分文字可能显示异常。')
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
    vi.mocked(convertPdfToWord).mockImplementation(() => new Promise(() => undefined))
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())
    const button = wrapper.find('button.convert-button')

    await button.trigger('click')
    await button.trigger('click')

    expect(vi.mocked(convertPdfToWord)).toHaveBeenCalledTimes(1)
  })

  it('keeps the OCR option off by default', async () => {
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob: new Blob(['docx']),
      filename: 'report.docx',
      fontsNormalized: true,
      ocrStatus: 'disabled',
    })

    const wrapper = mount(PdfToWordView)
    const checkbox = wrapper.find<HTMLInputElement>('input[type="checkbox"]')
    expect(checkbox.exists()).toBe(true)
    expect(checkbox.element.checked).toBe(false)
    expect(wrapper.text()).toContain('识别扫描页及图片中的文字（OCR）')

    await selectFile(wrapper, createPdfFile())
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(vi.mocked(convertPdfToWord)).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ ocrEnabled: false }),
    )
  })

  it('passes the OCR flag to the API when enabled', async () => {
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob: new Blob(['docx']),
      filename: 'scan.docx',
      fontsNormalized: true,
      ocrStatus: 'applied',
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('scan.pdf'))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(vi.mocked(convertPdfToWord)).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ ocrEnabled: true }),
    )
    expect(wrapper.text()).toContain('已识别扫描页中的文字')
    expect(wrapper.find('a.download-button').exists()).toBe(true)
  })

  it('warns about partially recognized pages and keeps the download', async () => {
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob: new Blob(['docx']),
      filename: 'partial.docx',
      fontsNormalized: true,
      ocrStatus: 'partial',
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('scan.pdf'))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('请复核识别结果')
    expect(wrapper.text()).toContain('部分内容未识别或可信度较低，请人工复核。')
    expect(wrapper.find('.status-panel.success').classes()).toContain('is-degraded')
    expect(wrapper.find('a.download-button').exists()).toBe(true)
  })

  it('reports font and OCR warnings independently', async () => {
    vi.mocked(convertPdfToWord).mockResolvedValue({
      blob: new Blob(['docx']),
      filename: 'both.docx',
      fontsNormalized: false,
      ocrStatus: 'partial',
    })

    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile('scan.pdf'))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('button.convert-button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('字体优化未成功')
    expect(wrapper.text()).toContain('部分内容未识别或可信度较低，请人工复核。')
    expect(wrapper.find('a.download-button').exists()).toBe(true)
  })

  it('disables the OCR option while converting', async () => {
    vi.mocked(convertPdfToWord).mockImplementation(() => new Promise(() => undefined))
    const wrapper = mount(PdfToWordView)
    await selectFile(wrapper, createPdfFile())

    const checkbox = wrapper.find<HTMLInputElement>('input[type="checkbox"]')
    expect(checkbox.attributes('disabled')).toBeUndefined()

    await wrapper.find('button.convert-button').trigger('click')

    expect(checkbox.attributes('disabled')).toBeDefined()
  })
})
