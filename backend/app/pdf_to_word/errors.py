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


ERROR_MESSAGES: dict[type[PdfToWordError], str] = {
    UnsupportedFileTypeError: "仅支持 PDF 文件，请选择有效的 PDF 文档。",
    EmptyFileError: "上传的文件为空，请选择有效的 PDF 文档。",
    FileTooLargeError: "文件过大，请上传小于 3 MB 的 PDF。",
    InvalidPdfError: "无法解析该 PDF 文件，请确认文件未损坏。",
    EncryptedPdfError: "该 PDF 已加密，暂不支持加密文件转换。",
    ScannedPdfError: "该 PDF 似乎是扫描件，暂不支持扫描版转换。",
    ConversionFailedError: "转换失败，请稍后重试。",
}
