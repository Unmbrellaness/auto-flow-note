"""
截图模块 - 负责捕获前台窗口
"""
import time
import threading
import queue
from typing import Optional, Tuple, Callable
from pathlib import Path
from PIL import Image

import win32gui
import win32api

from ..utils.logger import get_logger
from ..utils.config_loader import get_config


logger = get_logger("capture")


class ScreenCapturer:
    """
    屏幕捕获器 - 负责周期性捕获前台窗口
    使用生产者模式，将截图放入队列供消费者处理
    """
    
    def __init__(
        self,
        interval: float = None,
        queue_size: int = None,
        stop_event: threading.Event = None,
        output_queue: queue.Queue = None
    ):
        """
        初始化截图器
        
        Args:
            interval: 截屏间隔(秒)
            queue_size: 队列最大长度
            stop_event: 停止事件信号
            output_queue: 输出队列，如果为 None 则创建新队列
        """
        self.interval = interval or get_config('capture.interval', 0.2)
        self.queue_size = queue_size or get_config('capture.queue_size', 50)
        self._stop_event = stop_event or threading.Event()
        self._output_queue = output_queue or queue.Queue(maxsize=self.queue_size)
        
        # 统计信息
        self._frame_count = 0
        self._dropped_count = 0
        self._running = False
        
        logger.info(f"ScreenCapturer 初始化完成 | interval={self.interval}s")
    
    @property
    def output_queue(self) -> queue.Queue:
        """获取输出队列"""
        return self._output_queue
    
    @property
    def stop_event(self) -> threading.Event:
        """获取停止事件"""
        return self._stop_event
    
    def get_foreground_window_bbox(self) -> Optional[Tuple[int, int, int, int]]:
        """
        获取前台窗口的边界框
        
        Returns:
            (left, top, right, bottom) 或 None
        """
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd == 0:
                return None
            
            # 获取窗口在虚拟桌面上的位置
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            
            # 检查窗口是否有效
            if left == right or top == bottom:
                return None
            
            return (left, top, right, bottom)
        except Exception as e:
            logger.warning(f"获取前台窗口失败: {e}")
            return None
    
    def capture_screen(self, bbox: Tuple[int, int, int, int]) -> Optional[Image.Image]:
        """
        截取指定区域
        
        Args:
            bbox: (left, top, right, bottom)
            
        Returns:
            PIL Image 或 None
        """
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=bbox)
            return img
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None
    
    def run(self, duration: float = None):
        """
        运行截图器（作为生产者线程）
        
        Args:
            duration: 运行时长(秒)，None 表示无限直到停止
        """
        self._running = True
        self._frame_count = 0
        self._dropped_count = 0
        
        start_time = time.time()
        
        logger.info(f"📸 [Capture] 启动 | 频率: {1/self.interval:.1f} FPS | 时长: {duration}s")
        
        while not self._stop_event.is_set():
            # 检查是否超时
            if duration and (time.time() - start_time) >= duration:
                break
            
            # 获取前台窗口
            bbox = self.get_foreground_window_bbox()
            
            if bbox:
                img = self.capture_screen(bbox)
                if img:
                    timestamp = time.time()
                    
                    # 尝试放入队列
                    try:
                        self._output_queue.put_nowait((img, timestamp))
                        self._frame_count += 1
                    except queue.Full:
                        self._dropped_count += 1
                        logger.debug("队列已满，丢弃帧")
            
            # 控制截屏频率
            time.sleep(self.interval)
        
        self._running = False
        logger.info(f"📸 [Capture] 结束 | 捕获: {self._frame_count} | 丢弃: {self._dropped_count}")
    
    def stop(self):
        """停止截图"""
        self._stop_event.set()
    
    @property
    def stats(self) -> dict:
        """获取统计信息"""
        return {
            "frame_count": self._frame_count,
            "dropped_count": self._dropped_count,
            "running": self._running
        }


class CaptureThread(threading.Thread):
    """
    截图线程封装类
    方便作为独立线程启动
    """
    
    def __init__(self, capturer: ScreenCapturer = None, **kwargs):
        """
        初始化截图线程
        
        Args:
            capturer: ScreenCapturer 实例，如果为 None 则创建新实例
            **kwargs: 传递给 threading.Thread 的参数
        """
        name = kwargs.pop('name', 'CaptureThread')
        super().__init__(name=name, **kwargs)
        
        self._capturer = capturer or ScreenCapturer()
        self._stop_event = self._capturer.stop_event
    
    @property
    def capturer(self) -> ScreenCapturer:
        """获取捕获器实例"""
        return self._capturer
    
    @property
    def output_queue(self) -> queue.Queue:
        """获取输出队列"""
        return self._capturer.output_queue
    
    def run(self):
        """运行截图线程"""
        self._capturer.run()
    
    def stop(self):
        """停止截图线程"""
        self._capturer.stop()
