class PdfToWordError(Exception):
    """Base class for all pdf-to-word conversion errors."""


class UnsupportedFileTypeError(PdfToWordError):
    """The uploaded file is not a PDF."""


class EmptyFileError(PdfToWordError):
    """The uploaded file has no content."""


class FileTooLargeError(PdfToWordError):
    """The uploaded file exceeds the allowed size."""


class InvalidPdfError(PdfToWordError):
    """The file claims to be a PDF but cannot be parsed."""


class EncryptedPdfError(PdfToWordError):
    """The PDF is encrypted and requires a password."""


class ScannedPdfError(PdfToWordError):
    """The PDF appears to be a scanned image without extractable text."""


class ConversionFailedError(PdfToWordError):
    """The conversion engine failed to produce a DOCX."""


class OcrUnavailableError(PdfToWordError):
    """The OCR engine cannot be imported or initialized."""


class OcrFailedError(PdfToWordError):
    """Recognition failed while processing the document."""


class OcrPageLimitError(PdfToWordError):
    """The document needs recognition on more pages than allowed."""


class OcrNoTextError(PdfToWordError):
    """Recognition finished but produced no usable text."""


class PdfResourceLimitError(PdfToWordError):
    """The document exceeds the bounded conversion resource budget."""


class ConversionBusyError(PdfToWordError):
    """The isolated conversion worker is already processing a document."""


ERROR_MESSAGES: dict[type[PdfToWordError], str] = {
    PdfResourceLimitError: "文档页数、尺寸或图片资源过多，请拆分或缩小文件后重试。",
    ConversionBusyError: "转换服务正在处理其他文件，请稍后重试。",
    UnsupportedFileTypeError: "仅支持 PDF 文件，请选择有效的 PDF 文档。",
    EmptyFileError: "上传的文件为空，请选择有效的 PDF 文档。",
    FileTooLargeError: "文件过大，请上传小于 3 MB 的 PDF。",
    InvalidPdfError: "无法解析该 PDF 文件，请确认文件未损坏。",
    EncryptedPdfError: "该 PDF 已加密，暂不支持加密文件转换。",
    ScannedPdfError: "该 PDF 似乎是扫描件，请开启文字识别后再试。",
    ConversionFailedError: "转换失败，请稍后重试。",
    OcrUnavailableError: "文字识别服务暂时不可用，请稍后重试。",
    OcrFailedError: "文字识别失败，请稍后重试。",
    OcrPageLimitError: "需要识别的页数过多，请拆分文件后重试。",
    OcrNoTextError: "未能从该 PDF 中识别出文字，请确认文件内容清晰。",
}
