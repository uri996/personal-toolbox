import { describe, expect, it } from 'vitest'

import { convertPdfToWord, PdfToWordApiError } from './api'

function createPdfFile(name = 'report.pdf', size = 100, type = 'application/pdf'): File {
  const bytes = new Uint8Array(size)
  bytes[0] = 0x25
  bytes[1] = 0x50
  bytes[2] = 0x44
  bytes[3] = 0x46
  return new File([bytes], name, { type })
}

interface MockResponseOptions {
  status: number
  textBody?: string
  blobBody?: Blob
  contentType?: string
  contentDisposition?: string
  fontNormalization?: string
  ocrStatus?: string
}

function mockResponse(options: MockResponseOptions): Response {
  const headers = new Headers()
  if (options.contentType) {
    headers.set('Content-Type', options.contentType)
  }
  if (options.contentDisposition) {
    headers.set('Content-Disposition', options.contentDisposition)
  }
  if (options.fontNormalization) {
    headers.set('X-Font-Normalization', options.fontNormalization)
  }
  if (options.ocrStatus) {
    headers.set('X-Ocr-Status', options.ocrStatus)
  }
  return {
    ok: options.status >= 200 && options.status < 300,
    status: options.status,
    headers,
    text: async () => options.textBody ?? '',
    blob: async () =>
      options.blobBody ??
      new Blob([new Uint8Array(10)], { type: options.contentType }),
    json: async () => (options.textBody ? JSON.parse(options.textBody) : {}),
  } as unknown as Response
}

describe('convertPdfToWord', () => {
  it('uploads the file and returns a blob with the docx filename', async () => {
    const fetcher = (async () =>
      mockResponse({
        status: 200,
        contentType:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        contentDisposition: `attachment; filename="document.docx"; filename*=UTF-8''${encodeURIComponent('report.docx')}`,
        blobBody: new Blob(['docx'], { type: 'application/msword' }),
      })) as typeof fetch

    const result = await convertPdfToWord(createPdfFile('report.pdf'), { fetcher })

    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.filename).toBe('report.docx')
    expect(result.fontsNormalized).toBe(true)
    expect(result.ocrStatus).toBe('disabled')
  })

  it('sends ocr_enabled only when OCR is requested', async () => {
    const bodies: FormData[] = []
    const fetcher = (async (_url: string, init: RequestInit) => {
      bodies.push(init.body as FormData)
      return mockResponse({ status: 200, ocrStatus: 'applied' })
    }) as typeof fetch

    await convertPdfToWord(createPdfFile(), { fetcher })
    await convertPdfToWord(createPdfFile(), { fetcher, ocrEnabled: true })

    const [withoutOcr, withOcr] = bodies
    expect(withoutOcr?.has('ocr_enabled')).toBe(false)
    expect(withOcr?.get('ocr_enabled')).toBe('true')
  })

  it('reports OCR applied and partial statuses from response headers', async () => {
    const applied = (async () =>
      mockResponse({ status: 200, ocrStatus: 'applied' })) as typeof fetch
    const partial = (async () =>
      mockResponse({ status: 200, ocrStatus: 'partial' })) as typeof fetch

    await expect(
      convertPdfToWord(createPdfFile(), { fetcher: applied }),
    ).resolves.toMatchObject({ ocrStatus: 'applied' })
    await expect(
      convertPdfToWord(createPdfFile(), { fetcher: partial }),
    ).resolves.toMatchObject({ ocrStatus: 'partial' })
  })

  it('treats an unknown OCR status header as disabled', async () => {
    const fetcher = (async () =>
      mockResponse({ status: 200, ocrStatus: 'something-else' })) as typeof fetch

    const result = await convertPdfToWord(createPdfFile(), { fetcher })
    expect(result.ocrStatus).toBe('disabled')
  })

  it('marks the result as degraded when the server reports a font fallback', async () => {
    const fetcher = (async () =>
      mockResponse({
        status: 200,
        contentDisposition: 'attachment; filename="degraded.docx"',
        fontNormalization: 'fallback',
        blobBody: new Blob(['docx']),
      })) as typeof fetch

    const result = await convertPdfToWord(createPdfFile('report.pdf'), { fetcher })

    // The file is still delivered, but the caller must be told it needs review.
    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.filename).toBe('degraded.docx')
    expect(result.fontsNormalized).toBe(false)
  })

  it('falls back to the original pdf name when content-disposition is missing', async () => {
    const fetcher = (async () =>
      mockResponse({ status: 200, blobBody: new Blob(['x']) })) as typeof fetch

    const result = await convertPdfToWord(createPdfFile('notes.pdf'), { fetcher })

    expect(result.filename).toBe('notes.docx')
  })

  it('throws a user-facing error for non-ok responses with a json detail', async () => {
    const fetcher = (async () =>
      mockResponse({
        status: 400,
        contentType: 'application/json',
        textBody: JSON.stringify({ detail: '文件过大，请上传小于 3 MB 的 PDF。' }),
      })) as typeof fetch

    await expect(convertPdfToWord(createPdfFile(), { fetcher })).rejects.toThrow(
      PdfToWordApiError,
    )
    await expect(convertPdfToWord(createPdfFile(), { fetcher })).rejects.toThrow(
      '文件过大',
    )
  })

  it('throws a generic error for non-ok responses without json detail', async () => {
    const fetcher = (async () =>
      mockResponse({ status: 500, textBody: 'internal error' })) as typeof fetch

    await expect(convertPdfToWord(createPdfFile(), { fetcher })).rejects.toThrow(
      '转换失败',
    )
  })

  it('throws a network error when the request cannot be sent', async () => {
    const fetcher = (async () => {
      throw new TypeError('network down')
    }) as typeof fetch

    await expect(convertPdfToWord(createPdfFile(), { fetcher })).rejects.toThrow(
      '网络连接失败',
    )
  })

  it('does not swallow abort errors', async () => {
    const controller = new AbortController()
    const fetcher = (async () => {
      controller.abort()
      throw new DOMException('aborted', 'AbortError')
    }) as typeof fetch

    await expect(
      convertPdfToWord(createPdfFile(), { fetcher, signal: controller.signal }),
    ).rejects.toThrow(DOMException)
  })
})
