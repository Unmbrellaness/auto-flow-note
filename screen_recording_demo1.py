import cv2
import pyautogui
import numpy as np
import os
import time


def record_screen(duration_seconds=60, output_dir="recordings", filename="screen_record.mp4"):
    # 1. 创建保存目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    file_path = os.path.join(output_dir, filename)

    # 2. 获取屏幕尺寸
    screen_size = pyautogui.size()
    fps = 20.0  # 设定每秒帧数

    # 3. 设置视频编码器 (使用 mp4v 编码保存为 mp4)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(file_path, fourcc, fps, screen_size)

    print(f"开始录制... 预计时长: {duration_seconds}秒")
    print(f"文件将保存至: {file_path}")

    start_time = time.time()

    try:
        # 计算总帧数
        total_frames = int(duration_seconds * fps)

        for i in range(total_frames):
            # 获取屏幕截图
            img = pyautogui.screenshot()

            # 将图像转换为 numpy 数组，并从 RGB 转换为 BGR (OpenCV 使用 BGR)
            frame = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # 写入帧
            out.write(frame)

            # (可选) 如果你想手动停止，可以取消下面注释
            # if cv2.waitKey(1) == ord('q'): break

        print("录制完成！")

    except Exception as e:
        print(f"录制过程中出现错误: {e}")
    finally:
        # 释放资源
        out.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    # 设置录制 60 秒，并指定保存路径
    record_screen(duration_seconds=60 * 5, filename="my_recording_5min2.mp4")