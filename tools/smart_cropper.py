import os
import time
import cv2
import numpy as np
import psutil
import csv
from datetime import datetime
from PIL import ImageGrab

# ================= 配置区域 =================
OUTPUT_DIR = "captured_focus"
DELAY_SECONDS = 3
CAPTURE_INTERVAL = 1.0  # 截图间隔 (秒)
MAX_FRAMES = 20         # 最大处理帧数 (设为 -1 则无限运行)

# 变化检测阈值 (像素值差异超过此值视为变化)
MOTION_THRESHOLD = 5
# 最小变化区域面积 (避免噪点)
MIN_AREA_SIZE = 5000
# 文本密度网格大小 (将图像划分为 NxN 网格计算密度)
GRID_SIZE = 10
# =================================================

def get_performance_metrics(process):
    """获取当前进程的性能指标"""
    cpu_percent = process.cpu_percent(interval=None)
    mem_info = process.memory_info()
    return {
        'cpu': cpu_percent,
        'mem_mb': mem_info.rss / (1024 * 1024),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def calculate_text_density_mask(gray_img):
    """
    模拟文本密度检测：
    利用边缘检测和形态学操作寻找高频细节区域（通常对应文字）
    返回一个布尔掩膜，True 表示高密度区域
    """
    # 1. Canny 边缘检测
    edges = cv2.Canny(gray_img, 50, 150)
    
    # 2. 膨胀操作，连接断裂的文字笔画
    kernel = np.ones((3,3),np.uint8)
    dilated_edges = cv2.dilate(edges, kernel, iterations=2)
    
    # 3. 闭运算，填充文字内部空洞
    closed_edges = cv2.morphologyEx(dilated_edges, cv2.MORPH_CLOSE, kernel, iterations=1)
    
    return closed_edges > 0

def find_focus_region(frame_curr, frame_prev):
    """
    核心算法：结合变化检测和文本密度找到关注区域
    返回: (x, y, w, h) 或 None (如果无显著变化)
    """
    if frame_prev is None:
        return None

    # 1. 转换为灰度
    gray_curr = cv2.cvtColor(frame_curr, cv2.COLOR_RGB2GRAY)
    gray_prev = cv2.cvtColor(frame_prev, cv2.COLOR_RGB2GRAY)

    # 2. 变化检测 (帧差法)
    diff = cv2.absdiff(gray_prev, gray_curr)
    _, motion_mask = cv2.threshold(diff, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
    
    # 形态学操作去噪
    kernel = np.ones((5,5),np.uint8)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, kernel, iterations=2)
    motion_mask = cv2.dilate(motion_mask, kernel, iterations=2)

    # 3. 寻找变化区域的轮廓
    contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None

    # 找到最大的变化区域
    largest_contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest_contour)

    if area < MIN_AREA_SIZE:
        return None

    x, y, w, h = cv2.boundingRect(largest_contour)
    
    # 4. (可选优化) 在变化区域内进一步通过文本密度裁剪
    # 提取变化区域的 ROI
    roi_gray = gray_curr[y:y+h, x:x+w]
    if roi_gray.size == 0:
        return (x, y, w, h)
        
    density_mask = calculate_text_density_mask(roi_gray)
    
    # 如果密度掩膜全黑，说明变化区域可能是视频或纯色块，直接返回原变化区域
    if not np.any(density_mask):
        return (x, y, w, h)

    # 在密度掩膜中寻找最大的连通分量，进一步缩小范围
    # 这里简化处理：如果文本密度集中在某处，可以尝试再次 boundingRect
    # 为了稳定性，如果文本分布均匀，则保持原变化区域
    coords = cv2.findNonZero(density_mask.astype(np.uint8))
    if coords is not None:
        sub_x, sub_y, sub_w, sub_h = cv2.boundingRect(coords)
        # 只有当子区域明显小于原区域且包含足够内容时才裁剪，避免切得太碎
        if (sub_w * sub_h) > (w * h * 0.3): 
            return (x + sub_x, y + sub_y, sub_w, sub_h)

    return (x, y, w, h)

def main():
    # 初始化
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"✅ 创建输出目录: {OUTPUT_DIR}")

    print(f"⏳ 程序已启动，{DELAY_SECONDS} 秒后开始智能捕捉...")
    print(f"📂 结果将保存至: {os.path.abspath(OUTPUT_DIR)}")
    
    # 等待用户切换窗口
    for i in range(DELAY_SECONDS, 0, -1):
        print(f"   倒计时: {i}...", end='\r')
        time.sleep(1)
    print("\n🚀 开始工作！请滚动页面或输入命令...")

    # 性能监控初始化
    process = psutil.Process(os.getpid())
    perf_log = []
    # 预热 CPU 计数
    process.cpu_percent() 

    frame_count = 0
    prev_frame = None
    
    log_headers = ['Frame_ID', 'Timestamp', 'Status', 'Crop_Coords', 'Processing_Time_ms', 'CPU_Percent', 'Mem_MB']
    
    try:
        while True:
            start_time = time.time()
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

            # 1. 截屏 (全屏)
            screenshot = ImageGrab.grab()
            frame_np = np.array(screenshot)
            frame_rgb = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR) # OpenCV 默认 BGR

            # 2. 智能识别
            crop_coords = find_focus_region(frame_rgb, prev_frame)
            
            status = "No_Change"
            final_img = None
            coords_str = "None"

            if crop_coords:
                x, y, w, h = crop_coords
                coords_str = f"{x},{y},{w},{h}"
                status = "Cropped"
                # 执行裁剪
                final_img = frame_rgb[y:y+h, x:x+w]
                
                # 保存结果
                filename = f"frame_{frame_count:04d}_focus.png"
                save_path = os.path.join(OUTPUT_DIR, filename)
                cv2.imwrite(save_path, final_img)
                
                # 同时也保存一张缩略图示意原位置 (可选，调试用)
                # debug_img = frame_rgb.copy()
                # cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 3)
                # cv2.imwrite(os.path.join(OUTPUT_DIR, f"debug_{frame_count:04d}.png"), debug_img)
            else:
                # 如果没有变化，可以选择跳过保存，或者保存全屏标记为无变化
                # 这里选择跳过保存以节省空间，仅记录日志
                pass

            # 3. 更新上一帧
            prev_frame = frame_rgb

            # 4. 性能统计
            end_time = time.time()
            proc_time_ms = (end_time - start_time) * 1000
            metrics = get_performance_metrics(process)
            
            log_entry = {
                'Frame_ID': frame_count,
                'Timestamp': timestamp,
                'Status': status,
                'Crop_Coords': coords_str,
                'Processing_Time_ms': round(proc_time_ms, 2),
                'CPU_Percent': metrics['cpu'],
                'Mem_MB': round(metrics['mem_mb'], 2)
            }
            perf_log.append(log_entry)

            # 控制台输出
            if status == "Cropped":
                print(f"[{timestamp}] ✅ 检测到变化 -> 裁剪区域: {w}x{h} | 耗时: {proc_time_ms:.1f}ms")
            else:
                print(f"[{timestamp}] ⏸️  无明显变化 (跳过保存) | 耗时: {proc_time_ms:.1f}ms")

            frame_count += 1
            
            if MAX_FRAMES != -1 and frame_count >= MAX_FRAMES:
                print(f"\n🏁 已达到最大帧数限制 ({MAX_FRAMES})，停止运行。")
                break

            # 控制帧率
            sleep_time = max(0, CAPTURE_INTERVAL - (end_time - start_time))
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\n🛑 用户中断，正在保存性能日志...")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    finally:
        # 保存性能日志
        log_file = os.path.join(OUTPUT_DIR, "performance_log.csv")
        with open(log_file, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=log_headers)
            writer.writeheader()
            writer.writerows(perf_log)
        
        print(f"📊 性能日志已保存至: {log_file}")
        print(f"💾 共处理 {frame_count} 帧，其中有效裁剪 {sum(1 for l in perf_log if l['Status']=='Cropped')} 帧。")

if __name__ == "__main__":
    main()