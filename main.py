"""
Auto Flow Note - 主程序入口
自动化操作记录与AI分析工具

使用方法:
    python main.py                    # 使用默认配置运行
    python main.py --config my.yaml   # 使用自定义配置
    python main.py --help             # 查看帮助
"""
import os
import sys
import time
import threading
import queue
import signal
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.config_loader import load_config
from src.utils.logger import get_logger
from src.capture.screen_capturer import ScreenCapturer
from src.capture.change_detector import ChangeDetector
from src.analyzer.vision_recorder import QwenVisionRecorder


logger = get_logger("main", log_file="logs/app.log")


class AutoFlowNoteApp:
    """
    Auto Flow Note 应用主类
    整合截图、变化检测、AI分析功能
    
    使用生产者-消费者模式:
    - 生产者(CaptureThread): 负责高频截图
    - 消费者(AnalyzerThread): 负责去重、检测、分析、保存
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化应用
        
        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.config = load_config(config_path)
        
        # 初始化输出目录
        self._init_output_dirs()
        
        # 创建线程间通信队列
        capture_cfg = self.config.get('capture', {})
        queue_size = capture_cfg.get('queue_size', 50)
        self._capture_queue = queue.Queue(maxsize=queue_size)
        # AI 分析队列（用于解耦 AI 分析和文件保存）
        self._ai_queue = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        
        # 初始化各模块
        self._init_modules()
        
        # 统计信息
        self._running = False
        self._start_time = None
        
        # 注册信号处理（仅 Unix/Linux）
        self._register_signal_handler()
        
        logger.info("=" * 50)
        logger.info("AutoFlowNote 应用初始化完成")
        logger.info(f"基础输出目录: {self.base_output_dir.absolute()}")
        logger.info("=" * 50)
    
    def _init_output_dirs(self):
        """初始化输出目录（基础目录）"""
        # 基础输出目录
        self.base_output_dir = Path("outputs")
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        
        # 工作目录（每次录制时创建）
        self.work_dir = None
        self.raw_dir = None
        self.anno_dir = None
        self.debug_dir = None
        self.logs_dir = None
        self.topic_file = None
        
        logger.info(f"基础输出目录: {self.base_output_dir.absolute()}")
    
    def _create_work_dir(self):
        """创建本次录制的工作目录"""
        # 生成带时间戳的目录名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.work_dir = self.base_output_dir / f"session_{timestamp}"
        
        # 创建子目录
        self.raw_dir = self.work_dir / "raw"
        self.anno_dir = self.work_dir / "annotated"
        self.debug_dir = self.work_dir / "debug"
        self.logs_dir = self.work_dir / "logs"
        
        for dir_path in [self.raw_dir, self.anno_dir, self.debug_dir, self.logs_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # 创建主题文件
        self.topic_file = self.work_dir / "topic.txt"
        
        logger.info(f"工作目录已创建: {self.work_dir.absolute()}")
    
    def _init_modules(self):
        """初始化各功能模块"""
        # ========== 截图器 ==========
        capture_config = self.config.get('capture', {})
        self.capturer = ScreenCapturer(
            interval=capture_config.get('interval', 0.2),
            queue_size=capture_config.get('queue_size', 50),
            stop_event=self._stop_event,
            output_queue=self._capture_queue
        )
        
        # ========== 变化检测器 ==========
        detector_config = self.config.get('detector', {})
        self.detector = ChangeDetector(
            similarity_threshold=detector_config.get('similarity_threshold', 6),
            min_change_area=detector_config.get('min_change_area', 500),
            diff_threshold=detector_config.get('diff_threshold', 5),
            use_morphology=detector_config.get('use_morphology', True),
            debug_dir=str(self.debug_dir) if detector_config.get('save_debug', False) else None
        )
        
        # ========== AI 分析器 ==========
        aliyun_config = self.config.get('aliyun', {})
        analyzer_config = self.config.get('analyzer', {})
        
        self.analyzer = QwenVisionRecorder({
            'api_key': aliyun_config.get('api_key'),
            'model': aliyun_config.get('default_model', 'qwen-vl-max'),
            'temperature': analyzer_config.get('temperature', 0.1),
            'top_p': analyzer_config.get('top_p', 0.8),
            'topic_file': 'topic.txt',
            # 日志路径在工作目录创建后更新
        })
        
        if not self.analyzer.initialize():
            logger.warning("⚠️ AI 分析器初始化失败，将仅保存截图")
            self.analyzer = None
        else:
            logger.info(f"✅ AI 分析器初始化成功 | 模型: {self.config.get('aliyun', {}).get('default_model', 'qwen-vl-max')}")
    
    def _register_signal_handler(self):
        """注册信号处理"""
        if hasattr(signal, 'SIGINT'):
            try:
                signal.signal(signal.SIGINT, self._signal_handler)
            except Exception:
                pass
    
    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        logger.info("\n⚠️ 收到中断信号，正在停止...")
        self.stop()
    
    def _producer_thread(self):
        """生产者线程：截图"""
        logger.info("📸 [Producer] 启动")
        
        duration = self.config.get('capture', {}).get('duration', 60)
        self.capturer.run(duration)
        
        logger.info("📸 [Producer] 结束")
    
    def _consumer_thread(self):
        """消费者线程：处理截图"""
        logger.info("🧠 [Consumer] 启动")
        
        last_saved_img = None
        saved_count = 0
        analyzed_count = 0
        idle_count = 0  # 空闲计数
        max_idle = 10   # 连续空闲多少次后退出
        
        while True:
            # 检查是否需要停止：队列空 且 生产者已停止
            if self._capture_queue.empty() and self._stop_event.is_set():
                idle_count += 1
                if idle_count >= max_idle:
                    logger.info("🧠 [Consumer] 队列为空且生产者已停止，退出")
                    break
                time.sleep(0.5)
                continue
            
            idle_count = 0  # 重置计数
            
            try:
                img, timestamp = self._capture_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            
            try:
                # ========== 1. 生成文件名 ==========
                dt_str = datetime.fromtimestamp(timestamp).strftime('%H%M%S_%f')
                safe_time = dt_str[:-3]
                
                # ========== 2. 处理图片：去重 + 变化检测 ==========
                is_new, processed_img, bboxes = self.detector.process_frame(
                    img, 
                    last_saved_img,
                    save_prefix=f"debug_{saved_count:04d}_{safe_time}"
                )
                
                if not is_new:
                    # 相似帧，跳过
                    logger.debug(f"[跳过] #{saved_count:04d} 相似帧")
                    continue
                
                # ========== 3. 保存原图 ==========
                raw_path = self.raw_dir / f"shot_{saved_count:04d}_{safe_time}.png"
                img.save(raw_path)
                
                # ========== 4. 绘制变化区域标注 ==========
                if bboxes:
                    annotated_img = self.detector.draw_bboxes(img, bboxes)
                    anno_path = self.anno_dir / f"anno_{saved_count:04d}_{safe_time}.png"
                    annotated_img.save(anno_path)
                
                # 打印日志
                if bboxes:
                    bbox_info = ", ".join([f"{w}x{h}@({x},{y})" for x, y, w, h in bboxes])
                    logger.info(f"[💾 保存] #{saved_count:04d} | 变化区域: {bbox_info}")
                
                # ========== 5. 加入 AI 分析队列（异步处理）==========
                if self.analyzer and bboxes:
                    try:
                        # 将图片放入 AI 分析队列，不阻塞等待结果
                        self._ai_queue.put((img.copy(), saved_count, safe_time), timeout=1)
                        logger.debug(f"[🤖 AI] 加入分析队列: #{saved_count:04d}")
                    except queue.Full:
                        logger.warning(f"[🤖 AI] 队列已满，跳过分析: #{saved_count:04d}")
                
                # ========== 6. 更新参考图 ==========
                last_saved_img = img
                saved_count += 1
                
            except Exception as e:
                logger.error(f"处理帧时出错: {e}", exc_info=True)
                continue
        
        logger.info(f"🧠 [Consumer] 结束 | 保存: {saved_count} 张 | 分析: {analyzed_count} 次")
        
        # 打印统计信息
        self._print_stats()
    
    def _ai_worker_thread(self):
        """AI Worker 线程：从 AI 队列取图片并分析"""
        logger.info("🤖 [AI Worker] 启动")
        
        analyzed_count = 0
        idle_count = 0
        max_idle = 10  # 连续空闲多少次后退出
        
        while True:
            # 检查是否需要停止：队列空 且 两个条件满足之一：
            # 1. 生产者和消费者都已停止
            # 2. 或者超时强制退出
            if self._ai_queue.empty():
                # 检查生产者是否已停止
                if self._stop_event.is_set():
                    idle_count += 1
                    if idle_count >= max_idle:
                        logger.info("🤖 [AI Worker] 队列为空且录制已停止，退出")
                        break
                time.sleep(0.5)
                continue
            
            idle_count = 0
            
            try:
                img, saved_count, safe_time = self._ai_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            
            if not self.analyzer:
                continue
            
            try:
                logger.debug(f"[🤖 AI] 开始分析: #{saved_count:04d}")
                
                # AI 分析（同步等待结果）
                result = self.analyzer.analyze(img)
                
                analyzed_count += 1
                
                if result and result != "NO_RECORD":
                    # 自动保存到日志
                    self.analyzer._append_to_log(result)
                    # 截取前50字符展示
                    preview = result.split('\n')[0][:50]
                    logger.info(f"[🤖 AI] #{saved_count:04d}: {preview}...")
                elif result == "NO_RECORD":
                    logger.debug(f"[🤖 AI] #{saved_count:04d} 无有效内容")
                else:
                    logger.warning(f"[🤖 AI] #{saved_count:04d} 分析返回空")
                    
            except Exception as e:
                logger.error(f"[🤖 AI] 分析失败: #{saved_count:04d} - {e}")
        
        logger.info(f"🤖 [AI Worker] 结束 | 分析: {analyzed_count} 次")
        
        # AI Worker 结束时也打印统计
        if self.analyzer:
            logger.info(f"   分析器: {self.analyzer.stats}")
    
    def _print_stats(self):
        """打印统计信息"""
        logger.info("\n" + "=" * 50)
        logger.info("📊 统计信息:")
        logger.info(f"   截图器: {self.capturer.stats}")
        logger.info(f"   检测器: {self.detector.stats}")
        if self.analyzer:
            logger.info(f"   分析器: {self.analyzer.stats}")
        logger.info("=" * 50)
    
    def run(self):
        """运行应用"""
        # ========== 1. 创建工作目录 ==========
        self._create_work_dir()
        
        # 更新 analyzer 的日志路径
        if self.analyzer:
            self.analyzer.log_file = str(self.logs_dir / 'ai_analysis.txt')
        
        # 读取或输入主题
        topic = self.config.get('capture', {}).get('topic', '')
        if not topic:
            topic = input("请输入本次录制的主题（直接回车跳过）: ").strip()
        if topic:
            self.topic_file.write_text(topic, encoding='utf-8')
            logger.info(f"📋 主题: {topic}")
        
        # 显示启动信息
        duration = self.config.get('capture', {}).get('duration', 60)
        logger.info(f"\n🚀 开始录制 | 时长: {duration}s | 工作目录: {self.work_dir.name}\n")
        
        # 倒计时
        delay = self.config.get('capture', {}).get('delay_start', 3)
        for i in range(delay, 0, -1):
            print(f"   倒计时: {i}...", end='\r')
            time.sleep(1)
        print("\n🎬 开始录制!\n")
        
        self._running = True
        self._start_time = time.time()
        
        # ========== 启动线程 ==========
        
        # 生产者线程（截图）
        producer = threading.Thread(target=self._producer_thread, name="Producer")
        producer.start()
        
        # 消费者线程（处理图片+变化检测+保存）
        consumer = threading.Thread(target=self._consumer_thread, name="Consumer")
        consumer.start()
        
        # AI Worker 线程（分析图片）
        ai_worker = threading.Thread(target=self._ai_worker_thread, name="AIWorker")
        ai_worker.start()
        
        # 等待生产者结束
        producer.join()
        
        # 生产者结束后，设置停止事件，通知消费者退出
        self._stop_event.set()
        
        # 等待消费者处理完剩余数据
        consumer.join()
        
        # 消费者结束后，继续等待 AI Worker 处理完所有任务
        logger.info("⏳ 等待 AI 分析完成...")
        ai_worker.join()
        
        # 记录结束时间
        elapsed = time.time() - self._start_time
        self._running = False
        
        # ========== 2. 生成最终 Markdown 文件 ==========
        self._generate_markdown()
        
        logger.info(f"\n🎉 录制完成! 总耗时: {elapsed:.1f}s")
        logger.info(f"📁 工作目录: {self.work_dir.absolute()}")
        logger.info(f"📝 主题文件: {self.topic_file}")
        logger.info(f"📝 日志文件: {self.logs_dir / 'log.txt'}")
    
    def _generate_markdown(self):
        """生成最终的 Markdown 文件"""
        # 读取日志文件
        log_file = self.logs_dir / "log.txt"
        
        # 读取主题
        topic = ""
        if self.topic_file.exists():
            topic = self.topic_file.read_text(encoding='utf-8').strip()
        
        # 读取 AI 分析日志
        ai_log_file = self.logs_dir / "ai_analysis.txt"
        ai_content = ""
        if ai_log_file.exists():
            ai_content = ai_log_file.read_text(encoding='utf-8')
        
        # 生成 Markdown 内容
        md_content = f"""# {topic if topic else '自动化操作记录'}

## 基本信息

- **录制时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **录制时长**: {time.time() - self._start_time:.1f} 秒

## 主题

{topic if topic else '未指定'}

## AI 分析记录

{ai_content if ai_content else '无 AI 分析记录'}

## 输出文件

- 原始截图: `raw/`
- 标注图片: `annotated/`
- 调试图片: `debug/`
- 运行日志: `logs/`
"""
        
        # 保存 Markdown 文件
        md_file = self.work_dir / "README.md"
        md_file.write_text(md_content, encoding='utf-8')
        logger.info(f"📝 Markdown 文件已生成: {md_file}")
    
    def stop(self):
        """停止应用"""
        if not self._running:
            return
        
        logger.info("正在停止应用...")
        self._stop_event.set()
        
        # 等待一小段时间让线程结束
        time.sleep(1)
        
        self._running = False
        logger.info("应用已停止")


def main():
    """主函数入口"""
    parser = argparse.ArgumentParser(
        description="Auto Flow Note - 自动化操作记录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py
  python main.py --config my_config.yaml
  python main.py --duration 300
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='配置文件路径 (默认: config.yaml)'
    )
    
    parser.add_argument(
        '--duration', '-d',
        type=int,
        help='录制时长(秒)，会覆盖配置文件中的值'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='开启调试模式，保存中间图片'
    )
    
    args = parser.parse_args()
    
    # 检查配置文件是否存在
    if not Path(args.config).exists():
        print(f"❌ 配置文件不存在: {args.config}")
        print("请创建 config.yaml 或指定正确的配置文件路径")
        sys.exit(1)
    
    try:
        # 创建应用
        app = AutoFlowNoteApp(config_path=args.config)
        
        # 命令行参数覆盖配置
        if args.duration:
            app.config.setdefault('capture', {})['duration'] = args.duration
        
        if args.debug:
            app.config.setdefault('detector', {})['save_debug'] = True
        
        # 运行应用
        app.run()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ 用户中断")
    except Exception as e:
        logger.error(f"❌ 应用出错: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
