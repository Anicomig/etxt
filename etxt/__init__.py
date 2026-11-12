"""etxt —— 单文件加密文本工具。"""

from .crypto import EtxtError, NotEtxtFile, WrongPassword

__version__ = "0.1.0"
__all__ = ["EtxtError", "NotEtxtFile", "WrongPassword", "__version__"]
