const DEFAULT_API_BASE_URL = ''

export class PdfToWordApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PdfToWordApiError'
  }
}

export function getApiBaseUrl(configuredUrl = import.meta.env.VITE_API_BASE_URL): string {
  return (configuredUrl || DEFAULT_API_BASE_URL).replace(/\/+$/, '')
}

export type OcrStatus = 'disabled' | 'not-needed' | 'applied' | 'partial'

export interface ConvertResult {
  blob: Blob
  filename: string
  /**
   * False when the server produced a valid DOCX but its optional font repair
   * step failed. The file is still downloadable, but the user must be warned.
   */
  fontsNormalized: boolean
  /**
   * How OCR behaved. ``partial`` also includes retained low-confidence text
   * and failed regions whose original page image remains in the document.
   */
  ocrStatus: OcrStatus
}

export async function convertPdfToWord(
  file: File,
  options: {
    baseUrl?: string
    fetcher?: typeof fetch
    signal?: AbortSignal
    ocrEnabled?: boolean
  } = {},
): Promise<ConvertResult> {
  const fetcher = options.fetcher ?? fetch
  const formData = new FormData()
  formData.append('file', file)
  if (options.ocrEnabled) {
    formData.append('ocr_enabled', 'true')
  }

  let response: Response
  try {
    response = await fetcher(`${getApiBaseUrl(options.baseUrl)}/api/pdf-to-word/convert`, {
      method: 'POST',
      body: formData,
      signal: options.signal,
    })
  } catch (error) {
    if (options.signal?.aborted) {
      throw error
    }
    throw new PdfToWordApiError('网络连接失败，请检查网络后重试。')
  }

  if (!response.ok) {
    const message = await parseErrorMessage(response)
    throw new PdfToWordApiError(message)
  }

  const blob = await response.blob()
  const filename = parseFilename(response.headers.get('Content-Disposition'), file.name)
  const fontsNormalized = response.headers.get('X-Font-Normalization')?.toLowerCase() !== 'fallback'
  return { blob, filename, fontsNormalized, ocrStatus: parseOcrStatus(response) }
}

function parseOcrStatus(response: Response): OcrStatus {
  const value = response.headers.get('X-Ocr-Status')?.toLowerCase()
  if (value === 'applied' || value === 'partial' || value === 'not-needed') {
    return value
  }
  return 'disabled'
}

async function parseErrorMessage(response: Response): Promise<string> {
  const fallback = '转换失败，请稍后重试。'
  try {
    const text = await response.text()
    if (!text) {
      return fallback
    }
    const body = JSON.parse(text) as { detail?: string }
    if (typeof body.detail === 'string' && body.detail) {
      return body.detail
    }
  } catch {
    // fall through
  }
  return fallback
}

function parseFilename(contentDisposition: string | null, fallbackName: string): string {
  if (contentDisposition) {
    const starMatch = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition)
    const encodedName = starMatch?.[1]
    if (encodedName) {
      try {
        return decodeURIComponent(encodedName)
      } catch {
        // fall through
      }
    }
    const plainMatch = /filename="?([^";]+)"?/i.exec(contentDisposition)
    const plainName = plainMatch?.[1]
    if (plainName) {
      return plainName
    }
  }
  const dotIndex = fallbackName.lastIndexOf('.')
  const base = dotIndex > 0 ? fallbackName.slice(0, dotIndex) : fallbackName
  return `${base}.docx`
}
