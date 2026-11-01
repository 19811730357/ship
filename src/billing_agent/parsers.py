"""
文件解析器
支持EML、PDF、Excel、Word、TXT等格式
"""

from typing import Dict, Any, Optional
from pathlib import Path
import email
from email import policy
from email.parser import BytesParser
import PyPDF2
import pandas as pd
from docx import Document
from PIL import Image
import io


class DocumentParser:
    """文档解析器"""

    def __init__(self, ocr_enabled: bool = False, ocr_adapter=None):
        """
        初始化解析器

        Args:
            ocr_enabled: 是否启用OCR（需要外部服务）
            ocr_adapter: OCR适配器实例（用于识别图片和扫描件）
        """
        self.ocr_enabled = ocr_enabled
        self.ocr_adapter = ocr_adapter

    def parse_file(self, file_path: Path) -> Dict[str, Any]:
        """
        解析单个文件，根据扩展名自动选择解析器

        Args:
            file_path: 文件路径

        Returns:
            解析结果，格式：
            {
                "content": str,  # 主要文本内容
                "metadata": dict,  # 元数据
                "attachments": list,  # 附件信息（如果有）
                "source_file": str,  # 文件名
                "source_type": str  # 文件类型
            }
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = file_path.suffix.lower()

        if suffix == '.eml':
            return self.parse_eml(file_path)
        elif suffix == '.pdf':
            return self.parse_pdf(file_path)
        elif suffix in ['.xlsx', '.xls', '.csv']:
            return self.parse_excel(file_path)
        elif suffix in ['.docx', '.doc']:
            return self.parse_word(file_path)
        elif suffix == '.txt':
            return self.parse_txt(file_path)
        elif suffix in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']:
            return self.parse_image(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")

    def parse_eml(self, file_path: Path) -> Dict[str, Any]:
        """
        解析EML邮件文件

        Args:
            file_path: EML文件路径

        Returns:
            解析结果
        """
        with open(file_path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)

        # 提取基本信息
        subject = msg.get('subject', '')
        from_addr = msg.get('from', '')
        to_addr = msg.get('to', '')
        date = msg.get('date', '')

        # 提取正文
        body_parts = []
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))

                # 附件
                if 'attachment' in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append({
                            'filename': filename,
                            'content_type': content_type,
                            'size': len(part.get_payload(decode=True) or b'')
                        })
                # 正文
                elif content_type == 'text/plain':
                    body_parts.append(part.get_content())
                elif content_type == 'text/html':
                    # 简单处理HTML，保留文本部分
                    html_content = part.get_content()
                    # 可以用beautifulsoup清理，这里简化处理
                    body_parts.append(html_content)
        else:
            # 非multipart邮件
            body_parts.append(msg.get_content())

        content = '\n\n'.join(body_parts)

        return {
            'content': content,
            'metadata': {
                'subject': subject,
                'from': from_addr,
                'to': to_addr,
                'date': date,
                'has_attachments': len(attachments) > 0
            },
            'attachments': attachments,
            'source_file': file_path.name,
            'source_type': 'email'
        }

    def parse_pdf(self, file_path: Path) -> Dict[str, Any]:
        """
        解析PDF文件

        Args:
            file_path: PDF文件路径

        Returns:
            解析结果
        """
        content_parts = []
        metadata = {}

        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)

                # 提取元数据
                if pdf_reader.metadata:
                    metadata = {
                        'title': pdf_reader.metadata.get('/Title', ''),
                        'author': pdf_reader.metadata.get('/Author', ''),
                        'subject': pdf_reader.metadata.get('/Subject', ''),
                        'creator': pdf_reader.metadata.get('/Creator', ''),
                    }

                # 提取文本
                num_pages = len(pdf_reader.pages)
                metadata['num_pages'] = num_pages

                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if text.strip():
                        content_parts.append(f"[Page {page_num}]\n{text}")

            content = '\n\n'.join(content_parts)

            # 如果提取的文本很少，可能是扫描件，尝试OCR
            if len(content.strip()) < 50 and self.ocr_enabled:
                content = self._ocr_pdf(file_path, metadata)

        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")

        return {
            'content': content,
            'metadata': metadata,
            'attachments': [],
            'source_file': file_path.name,
            'source_type': 'pdf'
        }

    def _ocr_pdf(self, file_path: Path, metadata: dict) -> str:
        """
        使用OCR处理PDF扫描件
        注意：需要先将PDF文件上传到可访问的URL

        Args:
            file_path: PDF文件路径
            metadata: 元数据字典

        Returns:
            OCR识别的文本
        """
        if not self.ocr_adapter:
            return "[PDF文本提取较少，可能是扫描件。需要配置OCR服务进行识别]"

        return "[PDF扫描件检测到，但需要提供文件URL给OCR服务。请上传文件到服务器或OSS后使用]"

    def _extract_ocr_text(self, ocr_result: dict) -> str:
        """
        从OCR结果中提取文本

        Args:
            ocr_result: OCR服务返回的结果

        Returns:
            提取的文本
        """
        # 根据实际OCR服务返回格式调整
        # 这里假设返回格式为 {"data": {"text": "..."}} 或 {"data": [{"text": "..."}]}
        data = ocr_result.get('data', {})

        if isinstance(data, dict):
            return data.get('text', str(data))
        elif isinstance(data, list):
            texts = [item.get('text', '') for item in data if isinstance(item, dict)]
            return '\n'.join(texts)
        else:
            return str(data)

    def parse_excel(self, file_path: Path) -> Dict[str, Any]:
        """
        解析Excel/CSV文件

        Args:
            file_path: Excel文件路径

        Returns:
            解析结果
        """
        content_parts = []
        metadata = {}

        try:
            # 读取所有sheet
            if file_path.suffix.lower() == '.csv':
                df_dict = {'Sheet1': pd.read_csv(file_path)}
            else:
                df_dict = pd.read_excel(file_path, sheet_name=None)

            metadata['num_sheets'] = len(df_dict)
            metadata['sheet_names'] = list(df_dict.keys())

            # 转换为文本
            for sheet_name, df in df_dict.items():
                content_parts.append(f"=== {sheet_name} ===")
                content_parts.append(df.to_string(index=False))
                content_parts.append("")

            content = '\n'.join(content_parts)

        except Exception as e:
            raise ValueError(f"Excel解析失败: {str(e)}")

        return {
            'content': content,
            'metadata': metadata,
            'attachments': [],
            'source_file': file_path.name,
            'source_type': 'excel'
        }

    def parse_word(self, file_path: Path) -> Dict[str, Any]:
        """
        解析Word文档

        Args:
            file_path: Word文件路径

        Returns:
            解析结果
        """
        content_parts = []
        metadata = {}

        try:
            doc = Document(file_path)

            # 提取元数据
            core_props = doc.core_properties
            metadata = {
                'title': core_props.title or '',
                'author': core_props.author or '',
                'subject': core_props.subject or '',
                'created': str(core_props.created) if core_props.created else '',
                'modified': str(core_props.modified) if core_props.modified else '',
            }

            # 提取段落文本
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    content_parts.append(text)

            # 提取表格
            if doc.tables:
                content_parts.append("\n=== 表格数据 ===")
                for table_idx, table in enumerate(doc.tables, 1):
                    content_parts.append(f"\n[表格 {table_idx}]")
                    for row in table.rows:
                        row_text = '\t'.join(cell.text.strip() for cell in row.cells)
                        content_parts.append(row_text)

            content = '\n'.join(content_parts)

        except Exception as e:
            raise ValueError(f"Word解析失败: {str(e)}")

        return {
            'content': content,
            'metadata': metadata,
            'attachments': [],
            'source_file': file_path.name,
            'source_type': 'word'
        }

    def parse_txt(self, file_path: Path) -> Dict[str, Any]:
        """
        解析纯文本文件

        Args:
            file_path: 文本文件路径

        Returns:
            解析结果
        """
        try:
            # 尝试多种编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16']
            content = None

            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if content is None:
                raise ValueError("无法解码文本文件，尝试了多种编码")

        except Exception as e:
            raise ValueError(f"文本解析失败: {str(e)}")

        return {
            'content': content,
            'metadata': {
                'size': file_path.stat().st_size
            },
            'attachments': [],
            'source_file': file_path.name,
            'source_type': 'text'
        }

    def parse_image(self, file_path: Path) -> Dict[str, Any]:
        """
        解析图片文件（需要OCR）

        Args:
            file_path: 图片文件路径

        Returns:
            解析结果
        """
        try:
            img = Image.open(file_path)

            metadata = {
                'format': img.format,
                'size': img.size,
                'mode': img.mode
            }

            if self.ocr_enabled and self.ocr_adapter:
                content = "[图片文件检测到，但需要提供文件URL给OCR服务。请上传文件到服务器或OSS后使用]"
            else:
                content = f"[图片文件: {file_path.name}，尺寸 {img.size}，OCR未启用]"

        except Exception as e:
            raise ValueError(f"图片解析失败: {str(e)}")

        return {
            'content': content,
            'metadata': metadata,
            'attachments': [],
            'source_file': file_path.name,
            'source_type': 'image'
        }

    def parse_file_from_url(self, file_url: str, file_type: str = 'pdf') -> Dict[str, Any]:
        """
        从URL解析文件（使用OCR）
        适用于已经上传到服务器的文件

        Args:
            file_url: 文件URL
            file_type: 文件类型 (pdf/image)

        Returns:
            解析结果
        """
        if not self.ocr_enabled or not self.ocr_adapter:
            raise ValueError("OCR未启用，无法处理URL文件")

        try:
            # 调用OCR服务
            ocr_result = self.ocr_adapter.process_file(file_url, task="orderChange")

            # 解析OCR结果
            if ocr_result.get('code') == 0 or ocr_result.get('success'):
                ocr_text = self._extract_ocr_text(ocr_result)
                content = f"[OCR识别结果]\n{ocr_text}"
            else:
                error_msg = ocr_result.get('message', 'Unknown error')
                content = f"[OCR识别失败: {error_msg}]"

            return {
                'content': content,
                'metadata': {
                    'source_url': file_url,
                    'ocr_processed': True
                },
                'attachments': [],
                'source_file': file_url.split('/')[-1],
                'source_type': file_type
            }

        except Exception as e:
            raise ValueError(f"OCR处理失败: {str(e)}")
