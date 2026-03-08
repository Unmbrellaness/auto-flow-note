"""
配置加载器 - 统一管理配置加载
"""
import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path


class ConfigLoader:
    """配置加载器单例类"""
    
    _instance: Optional['ConfigLoader'] = None
    _config: Optional[Dict[str, Any]] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load(self, config_path: str = "config.yaml") -> Dict[str, Any]:
        """加载配置文件"""
        if self._config is not None:
            return self._config
            
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件未找到: {config_path}")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
        
        return self._config
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔的多级键"""
        if self._config is None:
            self.load()
        
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    def reload(self) -> Dict[str, Any]:
        """重新加载配置"""
        self._config = None
        return self.load()


# 全局配置加载器实例
_loader = ConfigLoader()


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """便捷函数：加载配置"""
    return _loader.load(config_path)


def get_config(key: str, default: Any = None) -> Any:
    """便捷函数：获取配置项"""
    return _loader.get(key, default)
