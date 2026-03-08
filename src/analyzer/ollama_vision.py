"""
Ollama 本地视觉分析器
使用本地 Ollama 运行的模型（如 qwen2.5-vl, llava 等）进行图像分析
"""
import time
from pathlib import Path
from typing import Optional, Dict, Any
from PIL import Image

from ..utils.logger import get_logger
from .base import BaseVisionAnalyzer

logger = get_logger("analyzer.ollama")


class OllamaVisionAnalyzer(BaseVisionAnalyzer):
    """
    使用本地 Ollama 的视觉分析器
    
    支持的模型（需要在 Ollama 中已下载）：
    - qwen2.5-vl 系列
    - llava 系列
    - moondream 系列
    - 及其他支持视觉的模型
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Ollama 分析器
        
        Args:
            config: 配置字典，应包含:
                - base_url: Ollama 服务地址 (默认 http://localhost:11434)
                - model: 模型名称 (默认 qwen2.5-vl:2b)
                - temperature: 温度参数
                - timeout: 请求超时时间
                - min_relevance: 最小相关度阈值
                - save_all_responses: 是否保存所有响应
                - topic_file: 主题文件路径
                - log_file: 日志文件路径
        """
        super().__init__(config)
        
        # Ollama 配置
        self.base_url = config.get('base_url', 'http://localhost:11434')
        self.model_name = config.get('model', 'qwen2.5-vl:2b')
        self.temperature = config.get('temperature', 0.1)
        self.top_p = config.get('top_p', 0.8)
        self.timeout = config.get('timeout', 120)
        
        # 相关度阈值
        self.min_relevance = config.get('min_relevance', 3)
        
        # 是否保存所有 AI 响应
        self.save_all_responses = config.get('save_all_responses', True)
        
        # 文件路径配置
        self.topic_file = config.get('topic_file', 'topic.txt')
        self.log_file = config.get('log_file', 'outputs/logs/log.txt')
        
        # System Prompt
        self.system_prompt = config.get('system_prompt', self._default_system_prompt())
        
        # Ollama 客户端（延迟导入）
        self._client = None
    
    @property
    def name(self) -> str:
        return "OllamaVisionAnalyzer"
    
    def _get_client(self):
        """延迟加载 Ollama 客户端"""
        if self._client is None:
            try:
                from ollama import chat
                self._client = chat
            except ImportError:
                logger.error("请安装 ollama 库: pip install ollama")
                raise ImportError("需要安装 ollama 库: pip install ollama")
        return self._client
    
    def _default_system_prompt(self) -> str:
        """默认的系统提示词"""
        return (
            "你是一名\"智能操作记录员\"。你的任务是根据用户屏幕图片和用户历史操作，理解用户正在做的事情，判断其与主题的相关程度，并转化为标准化的文字记录。\n"
            "核心原则：\n"
            "\n"
            " 相关度评分标准\n"
            "- 5分 (核心关键): 直接推动任务进展。包含具体命令执行、代码修改、关键配置确认、明确的报错及解决方案、登录/提交成功。\n"
            "- 4分 (重要过程): 必要的中间状态。如明显的进度变化(>10%)、表单填写、菜单选择、文件对话框操作。\n"
            "- 3分 (一般参考): 静态工作区或低信息量浏览。如IDE静止界面、文档阅读(无关键滚动)、简单的页面切换。\n"
            "- 2分 (轻微过渡): 与上一帧极度相似、鼠标微动、快速闪过的非关键弹窗、极短的加载过渡。\n"
            "- 1分 (无效噪音): 纯加载动画(转圈/进度条<5%)、黑/白屏、锁屏、无关广告、系统更新、完全重复的画面。\n"
            "\n"
            " ⚡ 处理规则\n"
            "1. 价值过滤：只记录有价值的操作步骤、关键配置、报错详情或解决方案。严格忽略纯进度条、加载动画、空白页或无实质变化的中间状态。\n"
            "2. 格式规范：严格遵循以下三行格式，不要包含任何 JSON、代码块标记（如 ```）、Markdown 符号（如 **）或额外的解释性文字：\n"
            "   [标题] <用一句简短的话概括用户操作>\n"
            "   [内容描述] <简要总结重要内容，如教程流程、报错信息或关键参数>\n"
            "   [主题相关度] <输出 1 到 5 的整数，1 表示完全不相关，5 表示高度相关>\n"
            "3. 语言风格：保持客观、简练，直接使用中文记录。\n"
            "4. 异常兜底：无论输入如何，只输出上述规定的格式内容，严禁输出\"好的\"、\"这是记录\"等废话。"
        )
    
    def initialize(self) -> bool:
        """初始化 Ollama 分析器"""
        try:
            # 尝试导入并检查连接
            client = self._get_client()
            
            # 标记为已初始化（main.py 会打印统一日志）
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"{self.name} 初始化失败: {e}")
            return False
    
    def _read_topic(self) -> str:
        """读取当前操作主题"""
        topic_path = Path(self.topic_file)
        
        if not topic_path.exists():
            default_topic = "默认任务主题"
            topic_path.write_text(default_topic, encoding='utf-8')
            return default_topic
        
        try:
            return topic_path.read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.warning(f"读取主题失败: {e}")
            return "默认任务主题"
    
    def _read_recent_history(self, max_lines: int = 20) -> str:
        """读取日志文件末尾的 N 行作为历史记录"""
        log_path = Path(self.log_file)
        
        if not log_path.exists():
            return "无历史记录，这是本次任务的第一步。"
        
        try:
            content = log_path.read_text(encoding='utf-8')
            lines = content.strip().split('\n')
            
            # 每条记录约 4 行
            recent_lines = lines[-(max_lines * 5):]
            
            if not recent_lines:
                return "无历史记录，这是本次任务的第一步。"
            
            return '\n'.join(recent_lines)
        except Exception as e:
            logger.warning(f"读取历史记录失败: {e}")
            return "读取历史记录出错。"
    
    def _save_temp_image(self, image: Image.Image) -> str:
        """保存 PIL Image 为临时文件路径，返回路径"""
        import tempfile
        import os
        
        # 创建临时文件
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"ollama_temp_{int(time.time()*1000)}.jpg")
        
        # 保存图片
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(temp_path, format='JPEG', quality=85)
        
        return temp_path
    
    def _parse_relevance(self, text: str) -> Optional[int]:
        """
        从 AI 输出中解析相关度评分
        """
        import re
        match = re.search(r'\[主题相关度\]\s*(\d+)', text)
        if match:
            score = int(match.group(1))
            if 1 <= score <= 5:
                return score
        return None
    
    def _append_to_log(self, content: str) -> bool:
        """将新记录追加到日志文件"""
        try:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"[时间] {timestamp}\n")
                f.write(content)
                f.write("\n\n")
            
            return True
        except Exception as e:
            logger.error(f"写入日志失败: {e}")
            return False
    
    def _append_all_responses(self, content: str, relevance: int = None) -> bool:
        """将所有 AI 响应追加到调试日志文件"""
        if not self.save_all_responses:
            return True
            
        try:
            log_path = Path(self.log_file)
            all_responses_path = log_path.parent / "all_responses.txt"
            all_responses_path.parent.mkdir(parents=True, exist_ok=True)
            
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            relevance_str = f"[相关度: {relevance}]" if relevance is not None else "[相关度: N/A]"
            
            with open(all_responses_path, 'a', encoding='utf-8') as f:
                f.write(f"[时间] {timestamp} {relevance_str}\n")
                f.write(content)
                f.write("\n\n")
            
            return True
        except Exception as e:
            logger.error(f"写入全部响应日志失败: {e}")
            return False
    
    def _build_messages(self, image: Image.Image, context: Dict[str, Any] = None) -> list:
        """构建 API 调用的消息"""
        # 读取上下文
        current_topic = context.get('topic') if context else self._read_topic()
        history_log = context.get('history') if context else self._read_recent_history()
        
        # 保存临时图片文件
        temp_image_path = self._save_temp_image(image)
        
        # 构建消息 - 使用官方 ollama 库格式
        prompt_text = (
            f"【当前任务主题】{current_topic}\n"
            f"【历史操作记录】\n{history_log}\n\n"
            "请分析图片并严格按三行格式输出([标题]\n、[内容描述]\n、[相关度]\n)"
        )
        
        messages = [
            {
                "role": "user",
                "content": prompt_text,
                "images": [temp_image_path]  # 使用文件路径
            }
        ]
        
        return messages
    
    def analyze(self, image: Image.Image, context: Dict[str, Any] = None) -> Optional[str]:
        """
        分析图片
        
        Args:
            image: PIL Image 对象
            context: 上下文信息
            
        Returns:
            分析结果或 None
        """
        self._ensure_initialized()
        
        temp_image_path = None
        try:
            client = self._get_client()
            messages = self._build_messages(image, context)
            
            # 调用 Ollama API
            response = client(
                model=self.model_name,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                }
            )
            
            # 处理响应
            raw_text = response.message.content.strip()
            
            # 清理可能的 Markdown 标记
            clean_text = raw_text.replace("```markdown", "").replace("```", "").strip()
            
            # 解析相关度
            relevance = self._parse_relevance(clean_text)
            
            # 保存所有 AI 响应
            self._append_all_responses(clean_text, relevance)
            
            # 检查相关度是否达到阈值
            if relevance is not None and relevance < self.min_relevance:
                logger.info(f"[🤖 AI] 相关度 {relevance} < {self.min_relevance}，跳过记录")
                self._record_success()
                return None
            
            self._record_success()
            return clean_text
                
        except Exception as e:
            logger.error(f"分析图片时发生异常: {e}")
            self._record_error()
            return None
        finally:
            # 清理临时文件
            if temp_image_path and Path(temp_image_path).exists():
                try:
                    Path(temp_image_path).unlink()
                except:
                    pass
    
    def analyze_from_file(self, image_path: str, context: Dict[str, Any] = None) -> Optional[str]:
        """
        从文件分析图片
        
        Args:
            image_path: 图片路径
            context: 上下文信息
            
        Returns:
            分析结果
        """
        if not Path(image_path).exists():
            logger.warning(f"图片文件不存在: {image_path}")
            return None
        
        try:
            img = Image.open(image_path)
            return self.analyze(img, context)
        except Exception as e:
            logger.error(f"打开图片失败: {e}")
            self._record_error()
            return None


# 注册到工厂
from .base import AnalyzerFactory
AnalyzerFactory.register('ollama', OllamaVisionAnalyzer)
