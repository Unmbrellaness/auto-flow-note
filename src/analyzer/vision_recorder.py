"""
Qwen Vision 分析器 - 基于阿里云 Qwen-VL 模型
"""
import os
import time
import base64
import io
from typing import Optional, Dict, Any
from pathlib import Path
from PIL import Image

import dashscope
from dashscope import MultiModalConversation

from .base import BaseVisionAnalyzer, AnalyzerFactory
from ..utils.logger import get_logger


logger = get_logger("qwen")


def pil_image_to_base64(image: Image.Image) -> str:
    """将 PIL Image 转换为 base64 字符串（data URL 格式）"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


class QwenVisionRecorder(BaseVisionAnalyzer):
    """
    Qwen Vision 记录器
    使用阿里云 Qwen-VL 模型分析屏幕截图
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Qwen 记录器
        
        Args:
            config: 配置字典，应包含:
                - api_key: 阿里云 API Key
                - model: 模型名称 (默认 qwen-vl-max)
                - temperature: 温度参数
                - top_p: top_p 参数
        """
        super().__init__(config)
        
        self.api_key = config.get('api_key')
        self.model_name = config.get('model', 'qwen3.5-flash')
        self.temperature = config.get('temperature', 0.1)
        self.top_p = config.get('top_p', 0.8)
        
        # 文件路径配置
        self.topic_file = config.get('topic_file', 'topic.txt')
        self.log_file = config.get('log_file', 'outputs/logs/log.txt')
        
        # System Prompt
        self.system_prompt = config.get('system_prompt', self._default_system_prompt())
    
    @property
    def name(self) -> str:
        return "QwenVisionRecorder"
    
    def _default_system_prompt(self) -> str:
        """默认的系统提示词"""
        return (
            """
            "你是一名"智能操作记录员"。你的任务是根据用户屏幕图片和用户历史操作，"
            "理解用户正在做的事情，判断其与主题的相关程度，并转化为标准化的文字记录。\n"
            "\n"
            " 相关度评分标准\n"
            "- 5分 (核心关键): 直接推动任务进展。\n"
            "- 4分 (重要过程): 必要的中间状态。\n"
            "- 3分 (一般参考): 静态工作区或低信息量浏览。\n"
            "- 2分 (轻微过渡): 与上一帧极度相似。\n"
            "- 1分 (无效噪音): 纯加载动画、黑/白屏、锁屏。\n"
            "\n"
            " ⚡ 处理规则\n"
            "1. 价值过滤：只记录有价值的操作步骤。\n"
            "2. 静默处理：如果无内容，输出 'NO_RECORD'。\n"
            "3. 格式规范：三行格式：[标题] / [内容描述] / [主题相关度]。\n"
            "4. 语言风格：保持客观、简练，直接使用中文记录。\n"
            """
        )
    
    def initialize(self) -> bool:
        """初始化 Qwen 记录器"""
        if not self.api_key:
            logger.error("未配置 API Key")
            return False
        
        if self.api_key == "sk-你的实际APIKey在这里":
            logger.error("请在配置文件中设置有效的 API Key")
            return False
        
        try:
            dashscope.api_key = self.api_key
            self._initialized = True
            logger.info(f"✅ QwenVision 初始化成功 | 模型: {self.model_name}")
            return True
        except Exception as e:
            logger.error(f"QwenVision 初始化失败: {e}")
            return False
    
    def _read_topic(self) -> str:
        """读取当前操作主题"""
        topic_path = Path(self.topic_file)
        
        if not topic_path.exists():
            default_topic = "默认任务主题"
            topic_path.write_text(default_topic, encoding='utf-8')
            return default_topic
        
        return topic_path.read_text(encoding='utf-8').strip()
    
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
    
    def _build_messages(self, image: Image.Image, context: Dict[str, Any] = None) -> list:
        """构建 API 调用的消息"""
        # 读取上下文
        current_topic = context.get('topic') if context else self._read_topic()
        history_log = context.get('history') if context else self._read_recent_history()
        
        # 将图片转为 base64
        image_base64 = pil_image_to_base64(image)
        
        user_prompt = f"""# 当前任务上下文
                        **操作主题**: {current_topic}
                        **历史操作记录**: 
                        {history_log}

                        # 当前屏幕图像分析指令
                        请分析上传的屏幕截图，结合"操作主题"和"历史操作记录"：
                        1. 状态识别: 识别当前屏幕显示的具体界面
                        2. 变化检测: 判断当前画面是否代表新的操作步骤
                        3. 价值评估: 判断该画面的记录价值
                        4. 生成记录: 
                        - 有价值：严格按三行格式输出（标题、内容描述、相关度1-5）
                        - 无价值：输出 'NO_RECORD'

                        注意：不要输出开场白或结束语。
                        """
                        
        messages = [
            {
                "role": "system",
                "content": [{"text": self.system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"image": image_base64},
                    {"text": user_prompt}
                ]
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
        
        try:
            messages = self._build_messages(image, context)
            
            response = MultiModalConversation.call(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                top_p=self.top_p
            )
            
            if response.status_code == 200:
                raw_text = response.output.choices[0].message.content[0]['text'].strip()
                
                # 清理 Markdown 标记
                clean_text = raw_text.replace("```markdown", "").replace("```", "").strip()
                
                # 检查是否为 NO_RECORD
                if "NO_RECORD" in clean_text:
                    self._record_success()
                    return "NO_RECORD"
                
                self._record_success()
                return clean_text
            else:
                logger.warning(f"API 调用失败: {response.code} - {response.message}")
                self._record_error()
                return None
                
        except Exception as e:
            logger.error(f"分析图片时发生异常: {e}")
            self._record_error()
            return None
    
    def analyze_from_file(self, image_path: str, context: Dict[str, Any] = None) -> Optional[str]:
        """
        从文件分析图片
        
        Args:
            image_path: 图片路径
            context: 上下文信息
            
        Returns:
            分析结果
        """
        if not os.path.exists(image_path):
            logger.warning(f"图片文件不存在: {image_path}")
            return None
        
        try:
            img = Image.open(image_path)
            return self.analyze(img, context)
        except Exception as e:
            logger.error(f"打开图片失败: {e}")
            self._record_error()
            return None
    
    def analyze_and_save(self, image: Image.Image, context: Dict[str, Any] = None) -> bool:
        """
        分析图片并自动保存到日志
        
        Args:
            image: PIL Image 对象
            context: 上下文信息
            
        Returns:
            是否成功保存
        """
        result = self.analyze(image, context)
        
        if result and result != "NO_RECORD":
            return self._append_to_log(result)
        
        return False


# 注册到工厂
AnalyzerFactory.register('qwen3.5-flash', QwenVisionRecorder)
# AnalyzerFactory.register('qwen-vl', QwenVisionRecorder)



