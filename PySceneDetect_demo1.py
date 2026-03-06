import os
from scenedetect import open_video, SceneManager, ContentDetector, StatsManager
from scenedetect.scene_manager import save_images


def extract_scenes_with_timestamps(video_path, output_dir="extracted_keyframes"):
    # 1. 初始化视频和管理器
    video = open_video(video_path)
    stats_manager = StatsManager()
    scene_manager = SceneManager(stats_manager)

    # 2. 添加内容检测器 (核心算法)
    # threshold 越低越灵敏。27-30 是通用值，如果你想捕捉更微小的文字输入变化，可以尝试 20-25。
    scene_manager.add_detector(ContentDetector(threshold=1.0))

    # 3. 执行检测
    print(f"正在分析视频: {video_path} ... 请稍候")
    scene_manager.detect_scenes(video)

    # 4. 获取检测到的场景列表
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        print("未检测到明显的场景变化。")
        return

    print(f"共检测到 {len(scene_list)} 个潜在的关键变化点。")

    # 5. 保存截图并命名
    # image_name_template 支持 $SCENE_NUMBER (序号), $TIMESTAMP (时间戳), $FRAME_NUMBER (帧数)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    save_images(
        scene_list=scene_list,
        video=video,
        num_images=1,  # 每个场景点只抓取 1 张图
        image_extension="jpg",  # 保存格式
        output_dir=output_dir,
        image_name_template="snapshot_$TIMESTAMP_MS"  # 文件名带上时间戳
    )

    print(f"提取完成！所有截图已保存至: {os.path.abspath(output_dir)}")


if __name__ == "__main__":
    # 填入你录制的视频路径
    target_video = "./recordings/my_recording.mp4"

    if os.path.exists(target_video):
        extract_scenes_with_timestamps(target_video)
    else:
        print(f"错误：找不到视频文件 {target_video}")