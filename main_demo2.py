import os
import sys
import re
import time
from datetime import datetime
# 引入你之前定义的类
from QwenVisionRecorder import QwenVisionRecorder

# ================= 配置区域 =================
INPUT_FOLDER = "extracted_keyframes_t=10"
OUTPUT_MD = "report_2.md"

# ===========================================

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


def parse_ai_response(text: str, image_path: str):
    """
    解析 AI 返回的文本，提取标题、描述和图片路径。
    预期格式：
    [标题] xxx
    [内容描述] xxx
    [主题相关度] x
    """
    if not text or "NO_RECORD" in text:
        return None

    # 清理可能的 Markdown 标记
    clean_text = text.replace("```markdown", "").replace("```", "").strip()

    title = ""
    desc = ""

    # 使用正则提取内容，兼容有无括号的情况
    # 匹配 [标题] 或 **标题** 或 标题:
    title_match = re.search(r'(?:\[标题\]|Title|标题)[:：\s]*(.+?)(?:\n|$)', clean_text)
    if title_match:
        title = title_match.group(1).strip()

    # 匹配 [内容描述] 或 Description 或 描述:
    desc_match = re.search(r'(?:\[内容描述\]|Description|描述|内容)[:：\s]*(.+?)(?:\n|$|\[)', clean_text, re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()

    # 如果正则没匹配到，尝试按行读取（兜底策略）
    if not title or not desc:
        lines = clean_text.split('\n')
        if len(lines) >= 2:
            # 假设第一行是标题，第二行是描述（去除可能的前缀）
            title = lines[0].replace('[标题]', '').replace('Title:', '').strip()
            desc = lines[1].replace('[内容描述]', '').replace('Description:', '').strip()

    if title and desc:
        return {
            "title": title,
            "desc": desc,
            "image": image_path
        }

    print(f"⚠️ 无法解析返回内容: {clean_text[:50]}...")
    return None


def main():
    # 1. 检查输入文件夹
    if not os.path.exists(INPUT_FOLDER):
        print(f"❌ 文件夹不存在：{INPUT_FOLDER}")
        return

    # 获取所有图片并排序
    valid_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
    # images = sorted([
    #     os.path.join(INPUT_FOLDER, f)
    #     for f in os.listdir(INPUT_FOLDER)
    #     if f.lower().endswith(valid_exts)
    # ])

    # 2. 获取图片列表
    image_files = get_sorted_images(INPUT_FOLDER)

    images = [os.path.join(INPUT_FOLDER, f) for f in image_files]

    if not images:
        print(f"⚠️ {INPUT_FOLDER} 中没有找到图片文件。")
        return

    print(f"🚀 开始处理 {len(images)} 张图片...")
    print(f"📂 输入目录：{os.path.abspath(INPUT_FOLDER)}")
    print(f"📝 报告输出：{os.path.abspath(OUTPUT_MD)}")
    print("-" * 30)

    try:
        # 2. 初始化 QwenVisionRecorder (自动加载 config.yaml, topic.txt)
        recorder = QwenVisionRecorder(config_path="config.yaml")

        # 打印当前主题确认
        current_topic = recorder._read_topic()
        print(f"📌 当前任务主题：{current_topic}")
        print("-" * 30)

        valid_records = []

        # 3. 循环处理
        for i, img_path in enumerate(images, 1):
            filename = os.path.basename(img_path)
            print(f"[{i}/{len(images)}] 🔍 分析：{filename} ...", end=" ", flush=True)

            # 调用类中的分析方法 (内部已包含读取历史和构建Prompt的逻辑)
            result_text = recorder.analyze_image(img_path)

            # 解析返回的文本
            parsed_data = parse_ai_response(result_text, img_path)

            if parsed_data:
                print(f"✅ 成功 (标题: {parsed_data['title'][:15]}...)")
                valid_records.append(parsed_data)

                # 关键步骤：将有效记录追加到 log.txt
                # 这样下一次运行或处理下一张图时，历史记录是更新的
                recorder._append_to_log(
                    f"[标题] {parsed_data['title']}\n"
                    f"[内容描述] {parsed_data['desc']}\n"
                    f"[主题相关度] 5"  # 既然被保留了，默认视为高相关，或者可以从解析中提取
                )
            else:
                print("⏭️ 跳过 (无价值/加载中)")

            # 可选：防止 API 限流
            # time.sleep(0.5)

        # 4. 生成 Markdown 报告
        print("-" * 30)
        print(f"✨ 处理完成！共提取 {len(valid_records)} 条有效记录。")
        print("🛠️ 正在生成 Markdown 报告...")

        md_content = f"# 📝 操作记录报告：{current_topic}\n\n"
        md_content += f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        md_content += f"*共分析 {len(images)} 张截图，筛选出 {len(valid_records)} 个关键步骤。*\n\n"
        md_content += "---\n\n"

        for idx, rec in enumerate(valid_records, 1):
            # 计算相对路径
            rel_img_path = os.path.relpath(rec['image'], start=os.path.dirname(os.path.abspath(OUTPUT_MD)))

            # 格式：二级标题 + 描述文本 + 图片
            md_content += f"## {idx}. {rec['title']}\n\n"
            md_content += f"{rec['desc']}\n\n"
            md_content += f"![{rec['title']}]({rel_img_path})\n\n"
            md_content += "---\n\n"

        with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
            f.write(md_content)

        print(f"🎉 成功！报告已保存至：{os.path.abspath(OUTPUT_MD)}")
        print(f"💾 结构化日志已同步更新至：{recorder.log_file}")
        print("\n💡 提示：用 Typora 或 VS Code 打开 report.md 查看效果。")

    except Exception as e:
        print(f"\n❌ 程序运行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()