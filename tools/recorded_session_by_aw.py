import os
import time
import threading
import queue
import win32gui
from PIL import ImageGrab
import imagehash
from datetime import datetime

# ================= 配置区域 =================
OUTPUT_DIR = "recorded_session_async"
DELAY_START = 3          # 启动延迟
RECORD_DURATION = 10     # 录制总时长
CAPTURE_INTERVAL = 0.3   # 截屏频率：【关键】截图频率提高至 0.3s (3fps)，确保捕捉所有瞬间
PROCESS_INTERVAL = 0.0   # 处理线程不休眠，有数据就处理
SIMILARITY_THRESHOLD = 5 # 哈希距离阈值
MAX_QUEUE_SIZE = 50      # 最大缓冲队列长度 (防止内存溢出)
# =================================================

# 全局队列：用于连接生产者和消费者
frame_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
stop_event = threading.Event() # 用于通知线程停止

def get_active_window_bbox():
    hwnd = win32gui.GetForegroundWindow()
    if hwnd == 0: return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if left == right or top == bottom: return None
    return (left, top, right, bottom)

def producer_thread(duration):
    """
    生产者：负责高频截图，只进队列，不做任何耗时操作
    """
    print(f"📸 [捕获线程] 启动，频率：{1/CAPTURE_INTERVAL} FPS")
    start_time = time.time()
    frame_count = 0
    dropped_count = 0

    while (time.time() - start_time) < duration and not stop_event.is_set():
        bbox = get_active_window_bbox()
        
        if bbox:
            try:
                # 极速截图
                img = ImageGrab.grab(bbox=bbox)
                timestamp = time.time() # 记录精确拍摄时间
                
                # 尝试放入队列
                try:
                    # put_nowait: 如果队列满了，不等待，直接抛出异常（代表丢帧，但保证不阻塞截图）
                    frame_queue.put_nowait((img, timestamp))
                    frame_count += 1
                except queue.Full:
                    dropped_count += 1
                    # 只有在极高负载下才会发生，说明处理线程太慢
            except Exception as e:
                pass # 截图失败忽略，继续下一帧
        else:
            time.sleep(0.05) # 没窗口稍微睡一下

        time.sleep(CAPTURE_INTERVAL)

    print(f"📸 [捕获线程] 结束。共捕获 {frame_count} 帧，因队列满丢弃 {dropped_count} 帧。")
    stop_event.set() # 通知消费者可以准备结束了

def consumer_thread():
    """
    消费者：负责从队列取图、去重、保存
    """
    print("🧠 [处理线程] 启动，等待数据...")
    last_saved_img = None
    saved_count = 0
    skipped_count = 0
    processed_count = 0

    # 循环直到：队列空了 且 生产者已经停止
    while True:
        try:
            # 获取数据，设置超时以便检查停止信号
            # 如果队列空了且生产者停了，就退出
            if frame_queue.empty() and stop_event.is_set():
                break
                
            img, timestamp = frame_queue.get(timeout=0.5)
            processed_count += 1
            
            # --- 核心去重逻辑 ---
            is_new_scene = True
            distance = 0
            
            if last_saved_img is not None:
                try:
                    distance = imagehash.phash(img) - imagehash.phash(last_saved_img)
                    if distance <= SIMILARITY_THRESHOLD:
                        is_new_scene = False
                        skipped_count += 1
                except Exception:
                    is_new_scene = True # 出错则强制保存

            # --- 保存逻辑 ---
            if is_new_scene:
                dt_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                filename = f"shot_{saved_count:04d}_{dt_str.replace(':','')}.png"
                save_path = os.path.join(OUTPUT_DIR, filename)
                
                img.save(save_path)
                # 可选：打印日志，生产环境可关闭以提高速度
                # print(f"[💾 保存] {filename} (差异度: {distance})")
                
                last_saved_img = img
                saved_count += 1
            
            # 标记任务完成
            frame_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ [处理线程] 错误: {e}")

    print("\n" + "="*30)
    print(f"🧠 [处理线程] 结束统计:")
    print(f"   处理总数: {processed_count}")
    print(f"   实际保存: {saved_count}")
    print(f"   去重跳过: {skipped_count}")
    print(f"   去重率:   {(skipped_count/processed_count*100):.1f}%" if processed_count > 0 else "   去重率: 0%")
    print("="*30)

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"✅ 创建输出目录: {OUTPUT_DIR}")

    print(f"⏳ 请在 {DELAY_START} 秒内切换到目标窗口...")
    for i in range(DELAY_START, 0, -1):
        print(f"   倒计时: {i}...", end='\r')
        time.sleep(1)
    print("\n🚀 开始异步智能录制！")

    # 1. 启动消费者线程（先启动，等着吃数据）
    t_consumer = threading.Thread(target=consumer_thread, name="Consumer")
    t_consumer.start()

    # 2. 启动生产者线程（开始干活）
    t_producer = threading.Thread(target=producer_thread, args=(RECORD_DURATION,), name="Producer")
    t_producer.start()

    # 3. 等待生产者结束
    t_producer.join()
    
    # 4. 等待消费者处理完队列中剩余的数据
    # 注意：这里需要给消费者一点时间处理完最后几帧
    t_consumer.join()

    print(f"\n🎉 全部完成！文件保存在: {os.path.abspath(OUTPUT_DIR)}")

if __name__ == "__main__":
    main()