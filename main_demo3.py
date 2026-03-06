import os
import sys
import re
import time
from datetime import datetime
# 引入你之前定义的类
from QwenVisionRecorder import QwenVisionRecorder

# ================= 配置区域 =================
INPUT_FOLDER = "extracted_keyframes"
OUTPUT_MD = "report_3.md"
# 设定阈值：低于此分数的图片在报告中将被折叠处理 (而不是直接丢弃)
FOLD_THRESHOLD = 4


# ===========================================

def get_sorted_images(folder_path: str) -> list:
    """
    获取文件夹内所有图片，并按文件名自然排序
    """

    def re_split(text):
        """辅助函数：用于自然排序"""
        import re
        return [int(c) if c.isdigit() else c.lower() for c in re.split('([0-9]+)', text)]

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


def parse_ai_response(text: str, image_path: str):
    """
    解析 AI 返回的文本。
    现在的逻辑：不检查 NO_RECORD，而是强制尝试提取分数、标题和描述。
    如果连分数都提取不到，则视为解析失败，赋予默认低分。
    """
    if not text:
        return create_default_record(image_path, score=1, title="解析失败", desc="AI 未返回有效内容")

    # 清理可能的 Markdown 标记
    clean_text = text.replace("```markdown", "").replace("```", "").strip()

    # 即使包含 NO_RECORD 字样，我们也尝试从中提取信息（以防 AI 啰嗦）
    # 但如果明确只有 NO_RECORD 且无其他结构，则给最低分
    if "NO_RECORD" in text and not re.search(r'\[主题相关度\]', text):
        # 兼容旧版 AI 行为：如果它还是回了 NO_RECORD，我们将其视为 1 分记录，而不是跳过
        return create_default_record(image_path, score=1, title="无价值画面", desc="AI 判定为无记录内容 (Loading/重复/空白)")

    title = ""
    desc = ""
    score = 3  # 默认分

    # 1. 提取分数 (关键)
    score_match = re.search(r'(?:\[主题相关度\]|Score|相关度)[:：\s]*(\d+)', clean_text)
    if score_match:
        try:
            score = int(score_match.group(1))
            score = max(1, min(5, score))  # 限制在 1-5
        except ValueError:
            score = 3

    # 2. 提取标题
    title_match = re.search(r'(?:\[标题\]|Title|标题)[:：\s]*(.+?)(?:\n|$)', clean_text)
    if title_match:
        title = title_match.group(1).strip()

    # 3. 提取描述
    desc_match = re.search(r'(?:\[内容描述\]|Description|描述|内容)[:：\s]*(.+?)(?:\n|$|\[)', clean_text, re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip()

    # 兜底策略：如果正则失败，尝试按行解析
    if not title or not desc:
        lines = clean_text.split('\n')
        # 简单启发式：找包含数字的行作为分数，第一行非数字行作为标题
        if len(lines) >= 2 and not title:
            title = lines[0].replace('[', '').replace(']', '').split(':')[-1].strip()
        if len(lines) >= 2 and not desc:
            # 找最长的一行作为描述
            desc_line = max(lines[1:], key=len) if len(lines) > 1 else lines[0]
            desc = desc_line.replace('[', '').replace(']', '').split(':')[-1].strip()

    # 如果最终还是没提取到标题，给一个默认值，但保留记录
    if not title:
        title = f"未命名操作 (得分:{score})"
    if not desc:
        desc = "无详细描述信息。"

    return {
        "title": title,
        "desc": desc,
        "score": score,
        "image": image_path
    }


def create_default_record(image_path, score, title, desc):
    """辅助函数：创建默认记录"""
    return {
        "title": title,
        "desc": desc,
        "score": score,
        "image": image_path
    }


def generate_md_segment(idx, rec, rel_img_path):
    """根据分数生成不同样式的 Markdown 片段"""
    score = rec['score']
    title = rec['title']
    desc = rec['desc']

    # 样式 1: 高分 (4-5 分) - 完全展开，高亮显示
    if score >= FOLD_THRESHOLD:
        return (
            f"## {idx}. {title} `⭐ (相关度:{score})`\n\n"
            f"{desc}\n\n"
            f"![{title}]({rel_img_path})\n\n"
            f"---\n\n"
        )

    # 样式 2: 中分 (2-3 分) - 折叠显示，点击查看详情
    elif score >= 2:
        label = "ℹ️ 参考步骤" if score == 3 else "⏸️ 过渡状态"
        return (
            f"### {idx}. {label}: {title} ` (相关度:{score})`\n\n"
            f"<details>\n"
            f"<summary>点击查看详细内容</summary>\n\n"
            f"{desc}\n\n"
            f"![{title}]({rel_img_path})\n\n"
            f"</details>\n\n"
            f"---\n\n"
        )

    # 样式 3: 低分 (1 分) - 深度折叠，仅保留索引和图片
    else:
        return (
            f"### {idx}. 🔇 噪音/无效画面 ` (相关度:{score})`\n\n"
            f"<details>\n"
            f"<summary>查看原始截图 (通常为空载、黑屏或重复)</summary>\n\n"
            f"**描述**: {desc}\n\n"
            f"![{title}]({rel_img_path})\n\n"
            f"</details>\n\n"
            f"---\n\n"
        )


def main():
    # 1. 检查输入文件夹
    if not os.path.exists(INPUT_FOLDER):
        print(f"❌ 文件夹不存在：{INPUT_FOLDER}")
        return

    # 获取所有图片并排序
    # valid_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
    # images = sorted([
    #     os.path.join(INPUT_FOLDER, f)
    #     for f in os.listdir(INPUT_FOLDER)
    #     if f.lower().endswith(valid_exts)
    # ])

    image_files = get_sorted_images(INPUT_FOLDER)
    images = [os.path.join(INPUT_FOLDER, f) for f in image_files]

    if not images:
        print(f"⚠️ {INPUT_FOLDER} 中没有找到图片文件。")
        return

    print(f"🚀 开始全量分析 {len(images)} 张图片 (基于评分筛选)...")
    print(f"📂 输入目录：{os.path.abspath(INPUT_FOLDER)}")
    print(f"📝 报告输出：{os.path.abspath(OUTPUT_MD)}")
    print("-" * 30)

    try:
        # 2. 初始化 QwenVisionRecorder
        recorder = QwenVisionRecorder(config_path="config.yaml")
        current_topic = recorder._read_topic()
        print(f"📌 当前任务主题：{current_topic}")
        print("-" * 30)

        all_records = []
        stats = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

        # 3. 循环处理 (全量记录，不再跳过)
        for i, img_path in enumerate(images, 1):
            filename = os.path.basename(img_path)
            print(f"[{i}/{len(images)}] 🔍 分析：{filename} ...", end=" ", flush=True)

            result_text = recorder.analyze_image(img_path)
            parsed_data = parse_ai_response(result_text, img_path)

            # 统计分数分布
            s = parsed_data.get('score', 3)
            stats[s] += 1

            # 全量追加到日志 (即使是 1 分也记录，保证时间线完整)
            recorder._append_to_log(
                f"[分数] {s}\n"
                f"[标题] {parsed_data['title']}\n"
                f"[内容描述] {parsed_data['desc']}\n\n"
            )

            all_records.append(parsed_data)
            print(f"✅ 已记录 (得分:{s})")

        # 4. 生成 Markdown 报告
        print("-" * 30)
        print(f"✨ 分析完成！分数分布统计:")
        print(f"   ⭐ 核心 (5分): {stats[5]} | 重要 (4分): {stats[4]}")
        print(f"   ️参考 (3分): {stats[3]} | ⏸️过渡 (2分): {stats[2]} | 🔇 噪音 (1分): {stats[1]}")

        high_quality_count = stats[4] + stats[5]
        print(f"💡 报告将重点展示 {high_quality_count} 条高价值记录，其余 {len(images) - high_quality_count} 条将折叠处理。")
        print("🛠️ 正在生成分级 Markdown 报告...")

        md_content = f"# 📝 智能操作审计报告：{current_topic}\n\n"
        md_content += f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"

        # 统计摘要
        md_content += "## 📊 内容概览\n"
        md_content += f"- **总截图数**: {len(images)}\n"
        md_content += f"- **高价值步骤 (4-5 分)**: {stats[4] + stats[5]} 张\n"
        md_content += f"- **参考/噪音 (1-3 分)**: {stats[1] + stats[2] + stats[3]} 张\n\n"
        md_content += "> 💡 **阅读指南**: 4-5 分内容直接展示；1-3 分内容已折叠，点击 `<summary>` 可查看细节。\n\n"
        md_content += "---\n\n"

        # 生成具体内容
        for idx, rec in enumerate(all_records, 1):
            rel_img_path = os.path.relpath(rec['image'], start=os.path.dirname(os.path.abspath(OUTPUT_MD)))
            segment = generate_md_segment(idx, rec, rel_img_path)
            md_content += segment

        with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
            f.write(md_content)

        print(f"🎉 成功！报告已保存至：{os.path.abspath(OUTPUT_MD)}")
        print(f"💾 全量日志已更新至：{recorder.log_file}")

    except Exception as e:
        print(f"\n❌ 程序运行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()