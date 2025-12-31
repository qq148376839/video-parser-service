"""
解密解析器模块
基于final_direct_parser_v2.py的解密方案（备选方案）
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from final_direct_parser_v2 import FinalDirectParserV2
from typing import Optional
import requests
import re
import os
from pathlib import Path
from datetime import datetime
from utils.logger import logger
from utils.m3u8_cleaner import M3U8Cleaner

# 项目根目录
project_root = Path(__file__).parent.parent


class DecryptParser:
    """解密解析器（备选方案）"""
    
    def __init__(self):
        """初始化解密解析器"""
        self.parser = FinalDirectParserV2()
        logger.info("解密解析器初始化完成")
    
    def parse(self, parser_url: str, video_url: str) -> Optional[str]:
        """
        解析视频URL，返回m3u8或mp4链接
        
        Args:
            parser_url: 解析网站URL
            video_url: 视频URL（如果包含$分隔的多集URL，只解析第一个）
        
        Returns:
            m3u8或mp4链接，如果失败返回None
        """
        try:
            # 处理多集URL：如果包含$且后面跟着http://或https://，只取第一个URL
            if '$' in video_url and ('$http://' in video_url or '$https://' in video_url):
                # 找到第一个$http://或$https://的位置
                first_episode_end = len(video_url)
                for marker in ['$http://', '$https://']:
                    idx = video_url.find(marker)
                    if idx != -1:
                        first_episode_end = min(first_episode_end, idx)
                
                if first_episode_end < len(video_url):
                    video_url = video_url[:first_episode_end]
                    logger.debug(f"检测到多集URL，只解析第一集: {video_url[:100]}...")
            
            logger.info(f"使用解密方案解析: {video_url}")
            result_url = self.parser.parse_video(parser_url, video_url)
            
            if result_url:
                # 检查返回的URL类型
                if '.m3u8' in result_url.lower():
                    logger.info(f"解密方案解析成功（m3u8）: {result_url[:100]}...")
                    # 下载并清理m3u8文件
                    cleaned_url = self._download_and_clean_m3u8(result_url)
                    if cleaned_url:
                        return cleaned_url
                    else:
                        return result_url
                elif '.mp4' in result_url.lower():
                    logger.info(f"解密方案解析成功（mp4）: {result_url[:100]}...")
                    # mp4链接也可以直接使用，返回它
                else:
                    logger.info(f"解密方案解析成功（其他格式）: {result_url[:100]}...")
                
                return result_url
            else:
                logger.warning("解密方案解析失败")
                return None
                
        except Exception as e:
            logger.error(f"解密方案解析异常: {e}")
            return None
    
    def _download_and_clean_m3u8(self, m3u8_url: str) -> Optional[str]:
        """
        下载m3u8文件并清理，返回清理后的文件路径或原始URL
        
        如果相同hash的文件已存在，直接返回现有文件，避免重复下载
        
        Args:
            m3u8_url: m3u8 URL
        
        Returns:
            清理后的m3u8文件路径（如果成功），否则返回None
        """
        # 保存到缓存目录
        cache_dir = project_root / "data" / "m3u8_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 从URL提取hash
        hash_match = re.search(r'/Cache/[^/]+/([a-f0-9]+)\.m3u8', m3u8_url)
        
        # 检查是否已有相同hash的文件存在
        if hash_match:
            hash_value = hash_match.group(1)
            # 查找所有以该hash开头的文件
            existing_files = list(cache_dir.glob(f"m3u8_{hash_value}_*.m3u8"))
            if existing_files:
                # 使用最新的文件（按修改时间）
                latest_file = max(existing_files, key=lambda p: p.stat().st_mtime)
                logger.info(f"解密解析器: 发现已存在的m3u8文件（hash={hash_value}），使用缓存: {latest_file}")
                return str(latest_file)
        
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            })
            
            # 下载m3u8文件
            response = session.get(m3u8_url, timeout=30)
            response.raise_for_status()
            m3u8_content = response.text
            
            # 清理m3u8内容
            cleaned_content = M3U8Cleaner.clean_m3u8_content(m3u8_content)
            
            # 生成文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            if hash_match:
                base_name = f"m3u8_{hash_match.group(1)}_{timestamp}"
            else:
                import hashlib
                hash_obj = hashlib.md5(m3u8_url.encode('utf-8'))
                base_name = f"m3u8_{hash_obj.hexdigest()[:16]}_{timestamp}"
            
            output_path = cache_dir / f"{base_name}.m3u8"
            
            # 保存文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)
            
            logger.info(f"解密解析器: m3u8文件已下载并清理: {output_path}")
            
            # 返回文件路径
            return str(output_path)
            
        except Exception as e:
            logger.warning(f"解密解析器: 下载m3u8文件失败: {e}，返回原始URL")
            return None

