import os
import time
import threading
import queue
import win32gui
from PIL import ImageGrab, ImageDraw, ImageFont
import imagehash
from datetime import datetime
import cv2
import numpy as np

# ================= 配置区域 =================
OUTPUT_DIR = "recorded_session_smart"
DELAY_START = 3          # 启动延迟
RECORD_DURATION = 5     # 录制总时长
CAPTURE_INTERVAL = 0.2   # 截屏频率：0.2s (5 FPS)，平衡速度与细节
SIMILARITY_THRESHOLD = 6 # 哈希距离阈值 (稍微调大一点，避免微小抖动触发)
MAX_QUEUE_SIZE = 50      # 最大缓冲队列长度

# 变化检测配置
MIN_CHANGE_AREA = 500    # 最小变化面积 (像素)，忽略噪点
DIFF_THRESHOLD = 5      # 像素差值阈值 (0-255)
# =================================================

# 全局队列
frame_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
stop_event = threading.Event()

def get_active_window_bbox():
    hwnd = win32gui.GetForegroundWindow()
    if hwnd == 0: return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if left == right or top == bottom: return None
    return (left, top, right, bottom)

def find_change_region(img_curr, img_prev, save_prefix=None):
    """
    核心算法：找出两张图片之间的所有差异区域 (Bounding Box)
    返回: [(x, y, w, h), ...] 或 None (如果无显著变化)
    save_prefix: 如果提供，保存中间状态图 (diff, thresh, closed)
    """
    if img_prev is None:
        return None

    # 1. 转换为 OpenCV 格式 (BGR) 和 NumPy 数组
    curr_np = cv2.cvtColor(np.array(img_curr), cv2.COLOR_RGB2BGR)
    prev_np = cv2.cvtColor(np.array(img_prev), cv2.COLOR_RGB2BGR)

    # 2. 转为灰度图 (减少计算量，关注结构变化而非颜色)
    gray_curr = cv2.cvtColor(curr_np, cv2.COLOR_BGR2GRAY)
    gray_prev = cv2.cvtColor(prev_np, cv2.COLOR_BGR2GRAY)

    # 3. 计算绝对差值
    diff = cv2.absdiff(gray_prev, gray_curr)

    # 4. 二值化 (只保留显著变化的像素)
    _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

    # 5. 形态学操作 (膨胀 + 腐蚀) -> 连接断裂的变化区域，去除噪点
    kernel = np.ones((5,5),np.uint8)
    dilated_thresh = cv2.dilate(thresh, kernel, iterations=2)
    closed_thresh = cv2.morphologyEx(dilated_thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

    # ===== 保存中间状态图 =====
    if save_prefix:
        # 保存绝对差值图 (转为彩色以便查看)
        diff_color = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
        cv2.imwrite(f"{save_prefix}_diff.png", diff_color)
        
        # 保存二值化图
        cv2.imwrite(f"{save_prefix}_thresh.png", thresh)
        
        # 保存形态学处理后的图
        cv2.imwrite(f"{save_prefix}_closed.png", closed_thresh)
    # ==========================

    # 6. 查找轮廓
    contours, _ = cv2.findContours(closed_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None

    # 7. 筛选所有满足最小面积要求的轮廓，返回所有边界框
    bboxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area >= MIN_CHANGE_AREA:
            x, y, w, h = cv2.boundingRect(contour)
            bboxes.append((x, y, w, h))

    if not bboxes:
        return None

    return bboxes

def draw_visual_annotation(img, bboxes):
    """
    可视化算法：在 PIL 图片上绘制多个红色矩形框
    bboxes: [(x, y, w, h), ...] 边界框列表
    """
    draw_img = img.copy()
    draw = ImageDraw.Draw(draw_img)
    
    # 支持单个 bbox 或 bbox 列表
    if isinstance(bboxes, tuple):
        bboxes = [bboxes]
    
    for bbox in bboxes:
        x, y, w, h = bbox
        # 绘制红色粗边框 (width=4)
        # 坐标格式：[(x1, y1), (x2, y2)]
        draw.rectangle([(x, y), (x + w, y + h)], outline="red", width=4)
    
    return draw_img

def producer_thread(duration):
    print(f"📸 [捕获线程] 启动，频率：{1/CAPTURE_INTERVAL} FPS")
    start_time = time.time()
    frame_count = 0
    dropped_count = 0

    while (time.time() - start_time) < duration and not stop_event.is_set():
        bbox = get_active_window_bbox()
        
        if bbox:
            try:
                img = ImageGrab.grab(bbox=bbox)
                timestamp = time.time()
                
                try:
                    frame_queue.put_nowait((img, timestamp))
                    frame_count += 1
                except queue.Full:
                    dropped_count += 1
            except Exception as e:
                pass
        else:
            time.sleep(0.05)

        time.sleep(CAPTURE_INTERVAL)

    print(f"📸 [捕获线程] 结束。共捕获 {frame_count} 帧，丢弃 {dropped_count} 帧。")
    stop_event.set()

def consumer_thread():
    print("🧠 [处理线程] 启动，等待数据...")
    last_saved_img = None # 用于比对的上一张“有效”图片
    saved_count = 0
    skipped_count = 0
    processed_count = 0

    while True:
        if frame_queue.empty() and stop_event.is_set():
            break
            
        try:
            img, timestamp = frame_queue.get(timeout=0.5)
            processed_count += 1
            
            # --- 1. 全局去重 (ImageHash) ---
            is_new_scene = True
            if last_saved_img is not None:
                try:
                    distance = imagehash.phash(img) - imagehash.phash(last_saved_img)
                    if distance <= SIMILARITY_THRESHOLD:
                        is_new_scene = False
                        skipped_count += 1
                except Exception:
                    is_new_scene = True

            if not is_new_scene:
                frame_queue.task_done()
                continue

            # --- 2. 局部变化检测 (找 BBox) ---
            # 即使通过了全局去重，我们也想知道具体哪里变了，以便标注
            # 注意：这里我们对比的是 "当前图" 和 "上一张已保存的图"
            # 先计算时间戳字符串
            dt_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
            safe_time = dt_str.replace(':','').replace('.','')
            # 构建中间图的保存路径前缀
            save_prefix = os.path.join(OUTPUT_DIR, f"debug_{saved_count:04d}_{safe_time}")
            bboxes = find_change_region(img, last_saved_img, save_prefix)
            
            # 如果全局哈希变了，但没检测到具体框（可能是全屏颜色微调），则使用全图作为框
            if bboxes is None:
                w, h = img.size
                bboxes = [(0, 0, w, h)]
            else:
                # 将所有小框合并为一个大框
                min_x = min(b[0] for b in bboxes)
                min_y = min(b[1] for b in bboxes)
                max_x = max(b[0] + b[2] for b in bboxes)
                max_y = max(b[1] + b[3] for b in bboxes)
                bboxes = [(min_x, min_y, max_x - min_x, max_y - min_y)]

            # --- 3. 生成可视化标注图 ---
            annotated_img = draw_visual_annotation(img, bboxes)

            # --- 4. 保存双文件 ---
            # safe_time 已在前面定义
            # 保存原图
            path_raw = os.path.join(OUTPUT_DIR, f"shot_{saved_count:04d}_{safe_time}.png")
            img.save(path_raw)
            
            # 保存标注图
            path_anno = os.path.join(OUTPUT_DIR, f"anno_{saved_count:04d}_{safe_time}.png")
            annotated_img.save(path_anno)

            # 打印日志
            bbox_info = ", ".join([f"{w}x{h}@({x},{y})" for x, y, w, h in bboxes])
            print(f"[💾 双存] #{saved_count:04d} | {len(bboxes)}个变化区域: {bbox_info}")

            # 更新参考图 (使用原始图，不是标注图)
            last_saved_img = img
            saved_count += 1
            
            frame_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ [处理线程] 错误: {e}")
            frame_queue.task_done()

    print("\n" + "="*30)
    print(f"🧠 [处理线程] 结束统计:")
    print(f"   有效保存: {saved_count} 组 (每组含原图 + 标注图 + 3张中间图)")
    print(f"   去重跳过: {skipped_count}")
    print(f"   输出目录: {os.path.abspath(OUTPUT_DIR)}")
    print("="*30)

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"✅ 创建输出目录: {OUTPUT_DIR}")

    print(f"⏳ 请在 {DELAY_START} 秒内切换到目标窗口...")
    for i in range(DELAY_START, 0, -1):
        print(f"   倒计时: {i}...", end='\r')
        time.sleep(1)
    print("\n🚀 开始智能录制 (原图 + 可视化标注)!")

    t_consumer = threading.Thread(target=consumer_thread, name="Consumer")
    t_consumer.start()

    t_producer = threading.Thread(target=producer_thread, args=(RECORD_DURATION,), name="Producer")
    t_producer.start()

    t_producer.join()
    t_consumer.join()

    print(f"\n🎉 全部完成！请查看文件夹：{OUTPUT_DIR}")
    print("💡 提示：将 'anno_*.png' 发送给 AI，效果最佳。")
    print("📊 中间状态图：'debug_*_diff.png' (差值图), 'debug_*_thresh.png' (二值化), 'debug_*_closed.png' (形态学)")

if __name__ == "__main__":
    main()