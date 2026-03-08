# 方案一：利用操作系统 API 获取“活动窗口”区域（最推荐，精度最高）
# 这是解决“写命令时背景不重要”最完美的方法。不要分析整张截图，而是先问操作系统“当前哪个窗口在焦点上”，然后只裁剪那个区域。
# 原理：调用 OS API 获取当前前景窗口（Foreground Window）的坐标 (x,y,w,h) ，然后只截取该矩形区域。
# 优点：100% 准确，计算成本几乎为零，直接去除任务栏、背景桌面和其他非活动窗口。
# Python 实现思路：
# Windows: 使用 pywin32 或 ctypes 调用 GetForegroundWindow 和 GetWindowRect。
# Mac: 使用 AppKit 或 quartz 获取 Frontmost Application 的窗口位置。
# Linux: 使用 Xlib 或 wnck 获取 Active Window。

# Windows 示例伪代码



import win32gui
from PIL import ImageGrab
import time

def capture_active_window():
    hwnd = win32gui.GetForegroundWindow()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    # 只截取活动窗口，自动忽略背景和边栏
    img = ImageGrab.grab(bbox=(left, top, right, bottom))
    # print(f"截取窗口: {left}, {top}, {right}, {bottom}")    
    # # 保存为png文件
    # img.save("active_window.png")
    return img, left, top, right, bottom

if __name__ == "__main__":
    print("3s后开始截取活动窗口")
    time.sleep(3)
    img, left, top, right, bottom = capture_active_window()
    print(f"截取窗口: {left}, {top}, {right}, {bottom}")
    img.show()