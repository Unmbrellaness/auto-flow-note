"""
AI分析器抽象基类 - 定义视觉分析器的接口
便于后期扩展其他模型
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path
from PIL import Image

from ..utils.logger import get_logger


logger = get_logger("analyzer")


class BaseVisionAnalyzer(ABC):
    """
    视觉分析器抽象基类
    所有具体的视觉分析器都应该继承此类
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化分析器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self._initialized = False
        
        # 统计信息
        self._total_analyzed = 0
        self._success_count = 0
        self._error_count = 0
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        初始化分析器（如加载模型、配置API等）
        
        Returns:
            初始化是否成功
        """
        pass
    
    @abstractmethod
    def analyze(self, image: Image.Image, context: Dict[str, Any] = None) -> Optional[str]:
        """
        分析单张图片
        
        Args:
            image: PIL Image 对象
            context: 上下文信息（如主题、历史记录等）
            
        Returns:
            分析结果字符串，或 None 表示分析失败
            返回 "NO_RECORD" 表示无有效内容需要记录
        """
        pass
    
    @abstractmethod
    def analyze_from_file(self, image_path: str, context: Dict[str, Any] = None) -> Optional[str]:
        """
        从文件分析图片
        
        Args:
            image_path: 图片文件路径
            context: 上下文信息
            
        Returns:
            分析结果字符串
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """获取分析器名称"""
        pass
    
    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized
    
    def _ensure_initialized(self):
        """确保已初始化，未初始化则自动初始化"""
        if not self._initialized:
            if not self.initialize():
                raise RuntimeError(f"{self.name} 初始化失败")
    
    @property
    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_analyzed": self._total_analyzed,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": f"{(self._success_count/self._total_analyzed*100):.1f}%" 
                            if self._total_analyzed > 0 else "0%"
        }
    
    def _record_success(self):
        """记录成功"""
        self._total_analyzed += 1
        self._success_count += 1
    
    def _record_error(self):
        """记录错误"""
        self._total_analyzed += 1
        self._error_count += 1


class AnalyzerFactory:
    """
    分析器工厂类
    用于创建不同类型的分析器
    """
    
    _analyzers = {}
    
    @classmethod
    def register(cls, name: str, analyzer_class: type):
        """
        注册分析器
        
        Args:
            name: 分析器名称
            analyzer_class: 分析器类
        """
        cls._analyzers[name] = analyzer_class
    
    @classmethod
    def create(cls, name: str, config: Dict[str, Any]) -> BaseVisionAnalyzer:
        """
        创建分析器
        
        Args:
            name: 分析器名称
            config: 配置字典
            
        Returns:
            分析器实例
        """
        if name not in cls._analyzers:
            raise ValueError(f"未知的分析器: {name}，可用: {list(cls._analyzers.keys())}")
        
        return cls._analyzers[name](config)
    
    @classmethod
    def available(cls) -> list:
        """获取可用的分析器列表"""
        return list(cls._analyzers.keys())
