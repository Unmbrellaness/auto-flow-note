import os
import sys
from datetime import datetime
from pathlib import Path

# 导入自定义模块
from QwenVisionRecorder import QwenVisionRecorder


def get_sorted_images(folder_path: str) -> list:
    """
    获取文件夹内所有图片，并按文件名自然排序
    """
    supported_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    files = []

    if not os.path.exists(folder_path):
        print(f"❌ 错误：文件夹不存在 -> {folder_path}")
        sys.exit(1)

    for f in os.listdir(folder_path):
        if f.lower().endswith(supported_extensions):
            files.append(f)

    # 自然排序 (避免 frame_10.png 排在 frame_2.png 前面)
    files.sort(key=re_split)
    return files



def re_split(text):
    """辅助函数：用于自然排序"""
    import re
    return [int(c) if c.isdigit() else c.lower() for c in re.split('([0-9]+)', text)]


def generate_markdown_report(input_folder: str, output_file: str):
    print(f"🚀 开始处理文件夹: {input_folder}")
    print(f"📄 输出目标: {output_file}")
    print("-" * 50)

    # 1. 初始化分析器 (自动注入配置)
    try:
        recorder = QwenVisionRecorder()
    except ValueError as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # 2. 获取图片列表
    image_files = get_sorted_images(input_folder)

    if not image_files:
        print("⚠️ 文件夹内没有找到任何图片文件。")
        return

    print(f"📸 发现 {len(image_files)} 张图片，开始逐帧分析...\n")

    # 3. 准备 Markdown 内容
    md_content = []
    md_content.append("# 📝 自动化操作全流程记录\n")
    md_content.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    md_content.append(f"**来源文件夹**: `{os.path.basename(os.path.abspath(input_folder))}`\n")
    md_content.append(f"**总帧数**: {len(image_files)}\n")
    md_content.append("---\n\n")

    stats = {"processed": 0, "skipped": 0, "errors": 0}

    # 4. 循环处理每一张图片
    for index, filename in enumerate(image_files, 1):
        image_path = os.path.join(input_folder, filename)
        print(f"[{index}/{len(image_files)}] 分析中: {filename} ...", end=" ")

        result_text = recorder.analyze_image(image_path)

        if result_text:
            # ✅ 有内容：写入 Markdown
            stats["processed"] += 1
            print("✅ 已记录")

            # 添加章节标题
            md_content.append(f"### 📍 步骤 {stats['processed']}: {filename}\n")

            # 添加图片预览 (相对路径或绝对路径，这里用相对路径方便查看)
            # 注意：Markdown 图片语法 ![alt](path)
            md_content.append(f"![{filename}]({image_path})\n")

            # 添加 AI 提取的文本内容
            md_content.append(f"{result_text}\n")
            md_content.append("---\n\n")

        else:
            # ⏭️ 无关键信息：跳过
            stats["skipped"] += 1
            print("⏭️  跳过 (无关键信息)")

    # 5. 生成统计摘要
    md_content.append("## 📊 统计摘要\n")
    md_content.append(f"- **有效记录**: {stats['processed']} 帧\n")
    md_content.append(f"- **自动跳过**: {stats['skipped']} 帧 (进度条/空白/重复)\n")
    md_content.append(f"- **处理成功率**: {(stats['processed'] / len(image_files) * 100):.1f}%\n")

    # 6. 写入文件
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("".join(md_content))

        print("\n" + "=" * 50)
        print(f"🎉 完成！报告已生成：{output_file}")
        print(f"   - 有效内容: {stats['processed']} 条")
        print(f"   - 忽略噪音: {stats['skipped']} 条")
        print("=" * 50)

    except Exception as e:
        print(f"❌ 写入文件失败: {e}")


if __name__ == "__main__":
    # 配置路径
    INPUT_DIR = "extracted_keyframes_t=10"
    OUTPUT_FILE = f"operation_"+datetime.now().strftime("%Y%m%d_%H%M%S") +".md"

    # 执行
    generate_markdown_report(INPUT_DIR, OUTPUT_FILE)