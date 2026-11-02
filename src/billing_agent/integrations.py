"""
外部服务集成
OCR和OSS适配器
"""

from .runtime import configure_runtime
configure_runtime()

from typing import Optional, Dict, Any
import os
import uuid
import requests
import oss2
from pathlib import Path
from .logger_config import get_ocr_logger

logger = get_ocr_logger()


class OCRAdapter:
    """OCR服务适配器"""

    def __init__(self):
        self.url = os.getenv("OCR_URL", "")
        self.token = os.getenv("OCR_TOKEN", "")
        self.token_header = os.getenv("OCR_TOKEN_HEADER", "Authorization")
        self.timeout_connect = int(os.getenv("OCR_CONNECT_TIMEOUT", "10"))
        self.timeout_read = int(os.getenv("OCR_TIMEOUT", "300"))

        logger.info(f"OCR Adapter initialized")
        logger.debug(f"  Token configured: {bool(self.token)}")
        logger.debug(f"  Timeout: {self.timeout_read}s")

    def is_configured(self) -> bool:
        """检查OCR是否已配置"""
        configured = bool(self.url)
        logger.debug(f"OCR configured: {configured}")
        return configured

    def process_file(
        self,
        file_url: str,
        task: str = "orderChange",
        callback: str = "",
        task_type: str = ""
    ) -> Dict[str, Any]:
        """
        处理文件OCR识别

        Args:
            file_url: 文件URL（支持PDF/图片）
            task: 任务类型，默认 orderChange
            callback: 回调URL（可选）
            task_type: 任务子类型（可选）

        Returns:
            OCR结果字典
        """
        logger.info(f"🔍 Starting OCR processing")
        logger.info(f"  Task: {task}")

        if not self.url:
            logger.error("❌ OCR_URL not configured")
            raise ValueError("OCR_URL未配置，无法调用OCR服务")

        data = {
            "file": file_url,
            "task": task,
            "callBack": callback,
            "taskType": task_type
        }

        headers = {}
        if self.token:
            value = self.token
            if self.token_header.lower() == "authorization" and not value.lower().startswith("bearer "):
                value = "Bearer " + value
            headers[self.token_header] = value

        try:
            response = requests.post(
                self.url,
                json=data,
                headers=headers,
                timeout=(self.timeout_connect, self.timeout_read)
            )
            response.raise_for_status()

            ocr_result = response.json()
            if not isinstance(ocr_result, dict):
                raise ValueError("OCR响应必须是JSON对象")
            logger.info("OCR response received; business result will be validated by parser")

            return ocr_result

        except requests.exceptions.Timeout as e:
            logger.error(f"❌ OCR request timeout (connect:{self.timeout_connect}s, read:{self.timeout_read}s)")
            raise TimeoutError("OCR请求超时，尚不能确定远端任务是否停止") from e
        except requests.exceptions.RequestException as e:
            logger.error("OCR request transport failed")
            raise RuntimeError("OCR网络请求失败") from e
        except ValueError as e:
            logger.error("OCR response format invalid")
            raise RuntimeError("OCR返回数据解析失败") from e

    def process_image(self, image_url: str) -> dict:
        """
        处理图片OCR（兼容旧接口）

        Args:
            image_url: 图片URL

        Returns:
            OCR结果
        """
        return self.process_file(image_url, task="orderChange")


class OSSAdapter:
    """阿里云OSS适配器"""

    def __init__(self):
        self.access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "")
        self.access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "")
        self.endpoint = os.getenv("OSS_ENDPOINT", "")
        self.bucket_name = os.getenv("OSS_BUCKET", "")

        self._bucket = None

    def is_configured(self) -> bool:
        """检查OSS是否已配置"""
        return all([
            self.access_key_id,
            self.access_key_secret,
            self.endpoint,
            self.bucket_name
        ])

    def _get_bucket(self):
        """获取或创建bucket实例"""
        if self._bucket is None:
            if not self.is_configured():
                raise ValueError("OSS凭证未配置完整")

            auth = oss2.Auth(self.access_key_id, self.access_key_secret)
            self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)

        return self._bucket

    def upload_file(self, local_path: str, object_name: str) -> str:
        """
        上传文件到OSS

        Args:
            local_path: 本地文件路径
            object_name: OSS对象名称

        Returns:
            文件的公网URL
        """
        bucket = self._get_bucket()

        try:
            # 上传文件
            with open(local_path, 'rb') as f:
                bucket.put_object(object_name, f)

            # 生成临时访问URL
            url = self.generate_presigned_url(object_name)
            return url

        except Exception as e:
            raise RuntimeError("OSS上传或URL签名失败") from e

    def generate_presigned_url(self, object_name: str, expires: int = 1800) -> str:
        """
        生成临时下载URL

        Args:
            object_name: OSS对象名称
            expires: 过期时间（秒），默认30分钟

        Returns:
            临时URL
        """
        bucket = self._get_bucket()

        try:
            url = bucket.sign_url('GET', object_name, expires)
            return url
        except Exception as e:
            raise RuntimeError("生成签名URL失败") from e

    def delete_file(self, object_name: str):
        """
        删除OSS文件

        Args:
            object_name: OSS对象名称
        """
        bucket = self._get_bucket()

        try:
            bucket.delete_object(object_name)
        except Exception as e:
            raise RuntimeError("删除OSS文件失败") from e

    def upload_and_get_url(self, local_path: str, prefix: str = "uploads/") -> str:
        """
        上传文件并返回临时URL（便捷方法）

        Args:
            local_path: 本地文件路径
            prefix: OSS路径前缀

        Returns:
            临时访问URL
        """
        file_path = Path(local_path)
        object_name = f"{prefix}{uuid.uuid4().hex}/{file_path.name}"
        return self.upload_file(local_path, object_name)
