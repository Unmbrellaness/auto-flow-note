import os
import yaml
import time
from typing import Optional
import dashscope
from dashscope import MultiModalConversation


class QwenVisionRecorder:
    def __init__(self, config_path: str = "config.yaml", model_name: Optional[str] = None):
        """
        初始化记录器，从 YAML 加载配置
        """
        self.config = self._load_config(config_path)

        # 获取 API Key
        self.api_key = self.config.get('aliyun', {}).get('api_key')
        if not self.api_key or self.api_key == "sk-你的实际APIKey在这里":
            raise ValueError("❌ 错误：请在 config.yaml 中配置有效的 aliyun.api_key")

        dashscope.api_key = self.api_key
        self.model_name = model_name or self.config.get('aliyun', {}).get('default_model', "qwen-vl-max")

        print(f"✅ 配置加载成功 | 模型: {self.model_name}")

        # 定义 System Prompt (保持不变)
        self.system_prompt = (
            "你是一名“智能操作记录员”。你的任务是根据用户屏幕图片和用户历史操作，理解用户正在做的事情，判断其与主题的相关程度，并转化为标准化的文字记录。\n"
            "核心原则：\n"
            "\n"
            " 相关度评分标准\n"
            "- 5分 (核心关键): 直接推动任务进展。包含具体命令执行、代码修改、关键配置确认、明确的报错及解决方案、登录/提交成功。\n"
            "- 4分 (重要过程): 必要的中间状态。如明显的进度变化(>10%)、表单填写、菜单选择、文件对话框操作。\n"
            "- 3分 (一般参考): 静态工作区或低信息量浏览。如IDE静止界面、文档阅读(无关键滚动)、简单的页面切换。\n"
            "- 2分 (轻微过渡): 与上一帧极度相似、鼠标微动、快速闪过的非关键弹窗、极短的加载过渡。\n"
            "- 1分 (无效噪音): 纯加载动画(转圈/进度条<5%)、黑/白屏、锁屏、无关广告、系统更新、完全重复的画面。\n"
            "\n"
            " ⚡ 处理规则\n"
            "1. 价值过滤：只记录有价值的操作步骤、关键配置、报错详情或解决方案。严格忽略纯进度条、加载动画、空白页或无实质变化的中间状态。\n"
            "2. 静默处理：如果当前画面没有任何值得记录的内容（即触发了原则 1 的忽略条件），请直接输出字符串 'NO_RECORD'，不要输出其他任何文字。\n"
            "3. 格式规范：若有内容记录，严格遵循以下三行格式，不要包含任何 JSON、代码块标记（如 ```）、Markdown 符号（如 **）或额外的解释性文字：\n"
            "   [标题] <用一句简短的话概括用户操作>\n"
            "   [内容描述] <简要总结重要内容，如教程流程、报错信息或关键参数>\n"
            "   [主题相关度] <输出 1 到 5 的整数，1 表示完全不相关，5 表示高度相关>\n"
            "4. 语言风格：保持客观、简练，直接使用中文记录。\n"
            "5. 异常兜底：无论输入如何，只输出上述规定的格式内容，严禁输出‘好的’、‘这是记录’等废话。"
        )

        # 配置文件路径
        self.topic_file = "topic.txt"
        self.log_file = "log.txt"

    def _load_config(self, path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"❌ 配置文件未找到：{path}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"❌ YAML 文件格式错误：{e}")

    def _read_topic(self) -> str:
        """读取当前操作主题"""
        if not os.path.exists(self.topic_file):
            # 如果文件不存在，创建一个默认的
            default_topic = "默认任务主题"
            with open(self.topic_file, 'w', encoding='utf-8') as f:
                f.write(default_topic)
            return default_topic

        with open(self.topic_file, 'r', encoding='utf-8') as f:
            return f.read().strip()

    def _read_recent_history(self, max_lines: int = 20) -> str:
        """读取日志文件末尾的 N 行作为历史记录"""
        if not os.path.exists(self.log_file):
            return "无历史记录，这是本次任务的第一步。"

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 每条记录大约 4 行，取最近 max_lines 条记录的文本量
            # 简单策略：直接取文件最后 max_lines * 5 行，防止空行干扰
            recent_lines = lines[-(max_lines * 5):]

            if not recent_lines:
                return "无历史记录，这是本次任务的第一步。"

            return "".join(recent_lines).strip()
        except Exception as e:
            print(f"⚠️ 读取历史记录失败：{e}")
            return "读取历史记录出错。"

    def _append_to_log(self, content: str):
        """将新记录追加到日志文件"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                # 添加时间戳和分隔
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                f.write(f"[时间] {timestamp}\n")
                f.write(content)
                f.write("\n\n")  # 两条换行符分隔不同记录
            return True
        except Exception as e:
            print(f"❌ 写入日志失败：{e}")
            return False

    def analyze_image(self, image_path: str) -> Optional[str]:
        """分析单张图片：读取上下文 -> 构建Prompt -> 调用AI -> 返回结果"""
        if not os.path.exists(image_path):
            print(f"⚠️ 文件不存在：{image_path}")
            return None

        # 1. 【读】实时从文件获取上下文
        current_topic = self._read_topic()
        history_log = self._read_recent_history()

        # 2. 【组】动态构建 User Prompt
        user_prompt = f"""
# 当前任务上下文
**操作主题**: {current_topic}
**历史操作记录**: 
{history_log}

# 当前屏幕图像分析指令
请分析上传的这张屏幕截图，结合上述“操作主题”和“历史操作记录”，执行以下思考步骤：
1. **状态识别**: 识别当前屏幕显示的具体界面、弹窗、报错信息或进度状态。
2. **变化检测**: 对比“历史操作记录”，判断当前画面是否代表了新的操作步骤、结果反馈或状态流转。如果是纯加载、空白或无变化，标记为无效。
3. **价值评估**: 判断该画面内容对于完成"{current_topic}"这一主题是否有实质性的记录价值。
4. **生成记录**: 
   - 如果有价值：严格按照系统要求的三行格式输出（标题、内容描述、相关度评分 1-5）。
   - 如果无价值：直接输出 'NO_RECORD'。

# 注意
- 不要复述我的输入信息。
- 不要输出任何开场白或结束语。
- 仅输出最终的分析结果。
"""

        messages = [
            {
                "role": "system",
                "content": [{"text": self.system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"image": f"file://{os.path.abspath(image_path)}"},
                    {"text": user_prompt}
                ]
            }
        ]

        try:
            response = MultiModalConversation.call(
                model=self.model_name,
                messages=messages,
                temperature=0.1,
                top_p=0.8
            )

            if response.status_code == 200:
                raw_text = response.output.choices[0].message.content[0]['text'].strip()

                # 清理可能的 Markdown 标记
                clean_text = raw_text.replace("```markdown", "").replace("```", "").strip()

                # 再次检查是否为 NO_RECORD (防止模型偶尔啰嗦)
                if "NO_RECORD" in clean_text:
                    return "NO_RECORD"

                return clean_text
            else:
                print(f"⚠️ API 调用失败：{response.code} - {response.message}")
                return None

        except Exception as e:
            print(f"⚠️ 发生异常：{str(e)}")
            return None


# ==========================================
# 主程序入口
# ==========================================
if __name__ == "__main__":
    # 测试图片列表 (请替换为你的实际截图路径)
    test_images = [
        "extracted_keyframes/snapshot_40700.jpg",
        # "extracted_keyframes/snapshot_40800.jpg",
        # 可以添加更多图片
    ]

    # 检查图片是否存在
    valid_images = [img for img in test_images if os.path.exists(img)]
    if not valid_images:
        print(f"⚠️ 未找到任何测试图片，请检查路径：{test_images}")
        # 为了演示，如果没有图片，创建一个空的 topic 和 log 文件
        if not os.path.exists("topic.txt"):
            with open("topic.txt", "w", encoding="utf-8") as f:
                f.write("搭建 react 环境并运行 demo")
        print("已创建默认 topic.txt，请放入真实图片后重新运行。")
        exit()

    try:
        # 1. 初始化
        recorder = QwenVisionRecorder(config_path="config.yaml")

        print(f"📝 开始处理 {len(valid_images)} 张图片...")
        print(f"📂 日志将保存至：{recorder.log_file}")
        print(f"📌 主题读取自：{recorder.topic_file}\n")

        for i, img_path in enumerate(valid_images, 1):
            print(f"[{i}/{len(valid_images)}] 🔍 正在分析：{os.path.basename(img_path)} ...")

            result = recorder.analyze_image(img_path)

            if result and result != "NO_RECORD":
                print(f"✅ 识别到有效操作，正在写入日志...")
                success = recorder._append_to_log(result)
                if success:
                    print(f"   💾 已追加到 {recorder.log_file}")
                else:
                    print(f"   ❌ 写入失败")
            else:
                print(f"⏭️  跳过 (无关键信息或加载中)")

            # 可选：避免频繁调用 API 被限流，可加一点延时
            # time.sleep(1)

        print("\n🎉 所有图片处理完成！")
        print(f"👉 请查看 {recorder.log_file} 获取完整记录。")

    except Exception as e:
        print(f"\n❌ 程序启动失败：{e}")