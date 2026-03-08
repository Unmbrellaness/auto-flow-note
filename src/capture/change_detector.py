"""
变化检测模块 - 检测图像变化并找出变化区域
"""
import os
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from PIL import Image, ImageDraw

import cv2
import numpy as np
import imagehash

from ..utils.logger import get_logger
from ..utils.config_loader import get_config


logger = get_logger("detector")


class ChangeDetector:
    """
    变化检测器 - 检测图像变化并找出变化区域
    1. 全局去重：使用感知哈希 (pHash) 过滤相似帧
    2. 局部变化检测：使用图像差分 + 形态学操作找出变化区域
    """
    
    def __init__(
        self,
        similarity_threshold: int = None,
        min_change_area: int = None,
        diff_threshold: int = None,
        use_morphology: bool = None,
        debug_dir: str = None
    ):
        """
        初始化变化检测器
        
        Args:
            similarity_threshold: 哈希相似度阈值，越小越严格
            min_change_area: 最小变化面积(像素)
            diff_threshold: 像素差值阈值 (0-255)
            use_morphology: 是否使用形态学去噪
            debug_dir: 调试图片保存目录
        """
        self.similarity_threshold = similarity_threshold or get_config('detector.similarity_threshold', 6)
        self.min_change_area = min_change_area or get_config('detector.min_change_area', 500)
        self.diff_threshold = diff_threshold or get_config('detector.diff_threshold', 5)
        self.use_morphology = use_morphology if use_morphology is not None else get_config('detector.use_morphology', True)
        self.debug_dir = debug_dir
        
        # 统计信息
        self._total_processed = 0
        self._skipped_similar = 0
        self._saved_count = 0
        
        logger.info(
            f"ChangeDetector 初始化完成 | "
            f"threshold={self.similarity_threshold}, "
            f"min_area={self.min_change_area}"
        )
    
    def compute_hash(self, img: Image.Image) -> imagehash.ImageHash:
        """
        计算图像的感知哈希
        
        Args:
            img: PIL Image
            
        Returns:
            ImageHash 对象
        """
        return imagehash.phash(img)
    
    def is_similar(self, img1: Image.Image, img2: Image.Image) -> bool:
        """
        判断两张图片是否相似
        
        Args:
            img1, img2: PIL Image
            
        Returns:
            True 表示相似（应跳过），False 表示不同（应保留）
        """
        hash1 = self.compute_hash(img1)
        hash2 = self.compute_hash(img2)
        
        distance = hash1 - hash2
        return distance <= self.similarity_threshold
    
    def find_change_regions(
        self, 
        img_curr: Image.Image, 
        img_prev: Image.Image,
        save_prefix: str = None
    ) -> Optional[List[Tuple[int, int, int, int]]]:
        """
        找出两张图片之间的所有差异区域 (Bounding Box)
        
        Args:
            img_curr: 当前图片
            img_prev: 上一张图片
            save_prefix: 调试图片保存前缀
            
        Returns:
            [(x, y, w, h), ...] 或 None (如果无显著变化)
        """
        if img_prev is None:
            return None
        
        # 1. 确保两张图片尺寸一致（以后一帧为准调整前一张）
        if img_curr.size != img_prev.size:
            img_prev = img_prev.resize(img_curr.size, Image.LANCZOS)
            logger.debug(f"调整图片尺寸: {img_prev.size} -> {img_curr.size}")
        
        # 2. 转换为 OpenCV 格式
        curr_np = cv2.cvtColor(np.array(img_curr), cv2.COLOR_RGB2BGR)
        prev_np = cv2.cvtColor(np.array(img_prev), cv2.COLOR_RGB2BGR)
        
        # 2. 转为灰度图
        gray_curr = cv2.cvtColor(curr_np, cv2.COLOR_BGR2GRAY)
        gray_prev = cv2.cvtColor(prev_np, cv2.COLOR_BGR2GRAY)
        
        # 3. 计算绝对差值
        diff = cv2.absdiff(gray_prev, gray_curr)
        
        # 4. 二值化
        _, thresh = cv2.threshold(diff, self.diff_threshold, 255, cv2.THRESH_BINARY)
        
        # 5. 开运算去除小白点噪声（可选）
        if self.use_morphology:
            kernel_open = np.ones((3, 3), np.uint8)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_open, iterations=1)
        
        # 6. 形态学操作：膨胀 + 腐蚀
        if self.use_morphology:
            kernel = np.ones((5, 5), np.uint8)
            dilated = cv2.dilate(thresh, kernel, iterations=2)
            thresh = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        # 保存调试图片
        if save_prefix and self.debug_dir:
            self._save_debug_images(save_prefix, diff, thresh, gray_curr, gray_prev)
        
        # 7. 查找轮廓
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None
        
        # 8. 筛选满足最小面积的轮廓
        bboxes = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= self.min_change_area:
                x, y, w, h = cv2.boundingRect(contour)
                bboxes.append((x, y, w, h))
        
        if not bboxes:
            return None
        
        return bboxes
    
    def _save_debug_images(
        self, 
        prefix: str, 
        diff: np.ndarray,
        thresh: np.ndarray,
        gray_curr: np.ndarray,
        gray_prev: np.ndarray
    ):
        """保存调试图片"""
        try:
            debug_path = Path(self.debug_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            
            # 保存差值图（彩色）
            diff_color = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
            cv2.imwrite(str(debug_path / f"{prefix}_diff.png"), diff_color)
            
            # 保存二值化图
            cv2.imwrite(str(debug_path / f"{prefix}_thresh.png"), thresh)
            
            # 保存形态学处理后的图
            if self.use_morphology:
                kernel = np.ones((5, 5), np.uint8)
                dilated = cv2.dilate(thresh, kernel, iterations=2)
                closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel, iterations=1)
                cv2.imwrite(str(debug_path / f"{prefix}_closed.png"), closed)
                
        except Exception as e:
            logger.warning(f"保存调试图片失败: {e}")
    
    def merge_bboxes(self, bboxes: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int, int]]:
        """
        合并多个边界框为一个大框
        
        Args:
            bboxes: [(x, y, w, h), ...]
            
        Returns:
            合并后的边界框列表
        """
        if not bboxes:
            return []
        
        if len(bboxes) == 1:
            return bboxes
        
        min_x = min(b[0] for b in bboxes)
        min_y = min(b[1] for b in bboxes)
        max_x = max(b[0] + b[2] for b in bboxes)
        max_y = max(b[1] + b[3] for b in bboxes)
        
        return [(min_x, min_y, max_x - min_x, max_y - min_y)]
    
    def draw_bboxes(self, img: Image.Image, bboxes: List[Tuple[int, int, int, int]]) -> Image.Image:
        """
        在图片上绘制边界框
        
        Args:
            img: PIL Image
            bboxes: [(x, y, w, h), ...]
            
        Returns:
            绘制了边界框的 Image
        """
        draw_img = img.copy()
        draw = ImageDraw.Draw(draw_img)
        
        for bbox in bboxes:
            x, y, w, h = bbox
            draw.rectangle([(x, y), (x + w, y + h)], outline="red", width=4)
        
        return draw_img
    
    def process_frame(
        self, 
        img: Image.Image, 
        last_img: Optional[Image.Image] = None,
        save_prefix: str = None
    ) -> Tuple[bool, Optional[Image.Image], Optional[List[Tuple[int, int, int, int]]]]:
        """
        处理单帧：先去重，再检测变化区域
        
        Args:
            img: 当前帧
            last_img: 上一帧（用于去重）
            save_prefix: 调试图片保存前缀
            
        Returns:
            (is_new_scene, processed_img, bboxes)
            - is_new_scene: 是否是新场景（需要保存）
            - processed_img: 处理后的图片（用于下次比对）
            - bboxes: 变化区域列表
        """
        self._total_processed += 1
        
        # 1. 全局去重
        if last_img is not None:
            if self.is_similar(img, last_img):
                self._skipped_similar += 1
                return False, img, None
        
        # 2. 局部变化检测
        bboxes = self.find_change_regions(img, last_img, save_prefix)
        
        # 如果全局哈希变了但没检测到具体框，使用全图
        if bboxes is None:
            w, h = img.size
            bboxes = [(0, 0, w, h)]
        else:
            # 合并所有小框为一个大框
            bboxes = self.merge_bboxes(bboxes)
        
        self._saved_count += 1
        return True, img, bboxes
    
    @property
    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_processed": self._total_processed,
            "skipped_similar": self._skipped_similar,
            "saved_count": self._saved_count,
            "skip_rate": f"{(self._skipped_similar/self._total_processed*100):.1f}%" 
                         if self._total_processed > 0 else "0%"
        }
