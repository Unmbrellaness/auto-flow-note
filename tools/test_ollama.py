from ollama import chat
from ollama import ChatResponse
import os
from PIL import Image, ImageDraw

# ================= 配置区域 =================
MODEL_NAME = 'qwen3-vl:2b'  # 你提供的模型名称
# MODEL_NAME = 'qwen3.5:2b'  # 你提供的模型名称
IMAGE_PATH = r"C:\Users\dyf\Desktop\auto-flow-note\auto-flow-note\extracted_keyframes\snapshot_18550.jpg"   # 测试图片路径
PROMPT_TEXT =  """你是一名“智能操作记录员”。你的任务是根据用户屏幕图片和用户历史操作，理解用户正在做的事情，判断其与主题的相关程度，并转化为标准化的文字记录。\n"
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
            "2. 格式规范：严格遵循以下三行格式，不要包含任何 JSON、代码块标记（如 ```）、Markdown 符号（如 **）或额外的解释性文字：\n"
            "   [标题] <用一句简短的话概括用户操作>\n"
            "   [内容描述] <简要总结重要内容，如教程流程、报错信息或关键参数>\n"
            "   [主题相关度] <输出 1 到 5 的整数，1 表示完全不相关，5 表示高度相关>\n"
            "3. 语言风格：保持客观、简练，直接使用中文记录。\n"
            "4. 异常兜底：无论输入如何，只输出上述规定的格式内容，严禁输出'好的'、'这是记录'等废话。"
            
            
            **操作主题**:
            **历史操作记录**: 
            请分析图片并严格按三行格式输出（[标题]\n、[内容描述]\n、[相关度]\n）
        """
# ===========================================

def prepare_image():
    """如果图片不存在，生成一张简单的测试图片"""
    if not os.path.exists(IMAGE_PATH):
        print(f"⚠️ 未找到 {IMAGE_PATH}，正在生成测试图片...")
        img = Image.new('RGB', (400, 300), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        
        # 画一个模拟窗口的矩形
        draw.rectangle([50, 50, 350, 250], outline="white", width=2)
        draw.text((70, 80), "Window Title: Settings", fill="white")
        draw.text((70, 120), "Status: Connected", fill="#00FF00")
        draw.text((70, 160), "Error: None detected", fill="#FF0000")
        
        img.save(IMAGE_PATH)
        print(f"✅ 测试图片已保存至: {IMAGE_PATH}")

def run_vision_test():
    # 1. 确保图片存在
    prepare_image()

    print(f"🚀 开始调用模型: {MODEL_NAME}")
    print(f"📷 图片: {IMAGE_PATH}")
    print(f"💬 问题: {PROMPT_TEXT}\n")
    print("⏳ AI 正在分析...\n")

    try:
        # 2. 构建请求 (完全遵循你的 Demo 格式)
        # 注意：images 字段接受文件路径列表
        response: ChatResponse = chat(
            model=MODEL_NAME, 
            messages=[
                {
                    'role': 'user',
                    'content': PROMPT_TEXT,
                    'images': [IMAGE_PATH]  # 这里是列表，可以放多张图 ['img1.jpg', 'img2.jpg']
                },
            ],
            # 如果需要流式输出，取消下面这行的注释，并参考下方的流式处理代码
            # stream=True 
        )

        # 3. 处理响应
        # 你的 Demo 是直接打印，这里做了更安全的访问
        if hasattr(response, 'message') and response.message:
            content = response.message.content
            print("✅ --- AI 回答 ---")
            print(content)
            print("---------------\n")
            
            # 如果你需要结构化数据（某些模型会返回 JSON），可以在这里解析
            return content
        else:
            print("⚠️ 返回的响应中没有找到 message 内容")
            return None

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        print("\n💡 排查建议:")
        print("1. 确认 Ollama 服务已启动 (ollama serve)")
        print("2. 确认模型已拉取或可用: ollama list")
        print("3. 如果是云端模型，检查网络连接或 API Key 配置")
        return None

def run_streaming_test():
    """如果你想看打字机效果，使用这个函数"""
    prepare_image()
    print("🚀 [流式模式] 开始调用...\n")
    
    try:
        stream = chat(
            model=MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': PROMPT_TEXT,
                'images': [IMAGE_PATH]
            }],
            stream=True
        )
        
        print("✅ --- AI 实时回答 ---")
        for chunk in stream:
            # 流式返回的 chunk 结构可能略有不同，通常直接有 message.content
            if 'message' in chunk and 'content' in chunk['message']:
                print(chunk['message']['content'], end='', flush=True)
        print("\n---------------\n")
        
    except Exception as e:
        print(f"\n❌ 流式测试失败: {e}")

if __name__ == "__main__":
    # 运行标准测试
    run_vision_test()
    
    # 如果想测试流式，取消下面这行的注释
    # run_streaming_test()