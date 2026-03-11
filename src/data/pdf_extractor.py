"""
PDF text extraction module for Chinese LOF fund announcements.

中国LOF基金公告PDF文本提取模块。

Uses pdfplumber for superior Chinese text support compared to PyPDF2.
Handles multi-page PDFs with page markers and graceful error handling.

使用pdfplumber进行PDF文本提取，相比PyPDF2具有更好的中文支持。
支持多页PDF，包含页面标记和优雅的错误处理。
"""

import logging
import sys
from pathlib import Path
from typing import Union

import pdfplumber

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    """Raised when PDF extraction fails."""

    pass


def _clean_text(text: str) -> str:
    """Clean and normalize extracted text.

    清理和规范化提取的文本。

    - Normalize whitespace (multiple spaces -> single) / 规范化空白（多个空格 -> 单个）
    - Preserve Chinese punctuation / 保留中文标点
    - Remove excessive newlines but keep paragraph structure / 移除过多换行但保留段落结构

    Args:
        text: Raw extracted text / 原始提取的文本

    Returns:
        Cleaned text / 清理后的文本
    """
    if not text:
        return ""

    # Replace multiple spaces with single space  # 将多个空格替换为单个空格
    import re

    text = re.sub(r" +", " ", text)

    # Replace 3+ newlines with 2 newlines (preserve paragraph breaks)  # 将3+换行替换为2换行（保留段落分隔）
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove leading/trailing whitespace from each line  # 移除每行首尾空白
    lines = [line.strip() for line in text.split("\n")]

    # Rejoin non-empty lines  # 重新连接非空行
    text = "\n".join(line for line in lines if line)

    return text.strip()


def extract_pdf_text(pdf_path: Union[Path, str]) -> dict:
    """Extract text from a PDF file using pdfplumber.

    使用pdfplumber从PDF文件中提取文本。

    pdfplumber is chosen over PyPDF2 for superior Chinese text handling
    and better support for financial documents with tables.

    选择pdfplumber而非PyPDF2，因为其对中文文本处理更好，
    对包含表格的金融文档支持更佳。

    Args:
        pdf_path: Path to the PDF file (Path object or string) / PDF文件路径

    Returns:
        Dict with keys: / 包含以下键的字典：
        - success (bool): Whether extraction succeeded / 提取是否成功
        - text (str): Extracted and cleaned text / 提取并清理后的文本
        - pages (int): Number of pages processed / 处理的页数
        - error (str | None): Error message if failed, None if succeeded / 错误信息（如失败），成功则为None
    """
    pdf_path = Path(pdf_path)

    logger.info(f"Attempting to extract text from PDF: {pdf_path}")

    result = {"success": False, "text": "", "pages": 0, "error": None}

    try:
        # Check if file exists  # 检查文件是否存在
        if not pdf_path.exists():
            error_msg = f"PDF file not found: {pdf_path}"
            logger.warning(error_msg)
            result["error"] = error_msg
            return result

        # Check if it's a file  # 检查是否为文件
        if not pdf_path.is_file():
            error_msg = f"Path is not a file: {pdf_path}"
            logger.warning(error_msg)
            result["error"] = error_msg
            return result

        # Open and extract text using pdfplumber  # 使用pdfplumber打开并提取文本
        all_pages_text = []
        page_count = 0

        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)

            for i, page in enumerate(pdf.pages, 1):
                # Extract text from page  # 从页面提取文本
                page_text = page.extract_text()

                if page_text:
                    all_pages_text.append(page_text)
                    # Add page marker between pages  # 在页面之间添加页面标记
                    if i < page_count:
                        all_pages_text.append(f"\n--- Page {i} ---\n")

        # Combine all pages  # 合并所有页面
        raw_text = "\n".join(all_pages_text)

        # Clean the text  # 清理文本
        cleaned_text = _clean_text(raw_text)

        result["success"] = True
        result["text"] = cleaned_text
        result["pages"] = page_count

        logger.info(f"Successfully extracted text from {page_count} pages: {pdf_path}")

    except pdfplumber.exceptions.PDFException as e:
        error_msg = f"PDF parsing error: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    except PermissionError as e:
        error_msg = f"Permission denied reading PDF: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    except Exception as e:
        error_msg = f"Unexpected error extracting PDF: {str(e)}"
        logger.warning(f"{error_msg} - File: {pdf_path}")
        result["error"] = error_msg

    return result


if __name__ == "__main__":
    # CLI mode for testing  # 命令行模式（用于测试）
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract text from PDF files using pdfplumber"
    )
    parser.add_argument("pdf_path", help="Path to the PDF file to extract text from")
    parser.add_argument(
        "-o", "--output", help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Extract text
    result = extract_pdf_text(args.pdf_path)

    if result["success"]:
        output = f"""Successfully extracted text from {result["pages"]} pages.

--- EXTRACTED TEXT ---

{result["text"]}
"""
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Text saved to: {args.output}")
        else:
            print(output)
    else:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
