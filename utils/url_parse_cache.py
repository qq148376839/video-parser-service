"""
URL解析缓存管理模块
负责URL解析结果的缓存读写、过期检查和缓存清理
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from utils.logger import logger
from utils.database import get_database
from utils.config_loader import config_loader


class URLParseCache:
    """URL解析缓存管理类"""
    
    def __init__(self):
        """初始化URL解析缓存管理器"""
        self.db = get_database()
        self.cache_time = config_loader.get_cache_time()
    
    def get_cache(self, video_url: str) -> Optional[Dict]:
        """
        获取URL解析缓存
        
        Args:
            video_url: 视频URL
        
        Returns:
            缓存记录（字典格式），如果不存在或已过期返回None
        """
        try:
            # 规范化URL（去除末尾的斜杠和空格）
            normalized_url = video_url.strip().rstrip('/')
            
            # 查询缓存
            record = self.db.execute_one(
                """
                SELECT video_url, m3u8_url, m3u8_file_path, file_id, parse_method, 
                       created_at, updated_at, expire_at, hit_count
                FROM url_parse_cache
                WHERE video_url = ?
                """,
                (normalized_url,)
            )
            
            if not record:
                logger.debug(f"URL解析缓存未命中: {normalized_url[:100]}...")
                return None
            
            # 检查是否过期
            expire_at_str = record.get('expire_at')
            if expire_at_str:
                try:
                    expire_at = datetime.fromisoformat(expire_at_str)
                    if datetime.now() > expire_at:
                        logger.debug(f"URL解析缓存已过期: {normalized_url[:100]}...")
                        return None
                except Exception as e:
                    logger.debug(f"解析过期时间失败: {e}，视为未过期")
            
            # 更新命中次数
            self.db.execute_update(
                """
                UPDATE url_parse_cache 
                SET hit_count = hit_count + 1, updated_at = datetime('now')
                WHERE video_url = ?
                """,
                (normalized_url,)
            )
            
            logger.info(f"URL解析缓存命中: {normalized_url[:100]}... (命中次数: {record.get('hit_count', 0) + 1})")
            
            return {
                'video_url': record['video_url'],
                'm3u8_url': record['m3u8_url'],
                'm3u8_file_path': record.get('m3u8_file_path'),
                'file_id': record.get('file_id'),
                'parse_method': record.get('parse_method'),
                'created_at': record.get('created_at'),
                'updated_at': record.get('updated_at'),
                'hit_count': record.get('hit_count', 0) + 1
            }
            
        except Exception as e:
            logger.error(f"获取URL解析缓存失败: {e}", exc_info=True)
            return None
    
    def save_cache(self, video_url: str, m3u8_url: str, m3u8_file_path: Optional[str] = None,
                   file_id: Optional[str] = None, parse_method: Optional[str] = None,
                   expire_hours: Optional[int] = None) -> bool:
        """
        保存URL解析结果到缓存
        
        Args:
            video_url: 视频URL
            m3u8_url: 解析得到的m3u8 URL（本地API接口URL）
            m3u8_file_path: m3u8文件路径（可选）
            file_id: 文件ID（可选）
            parse_method: 解析方法（可选，如 'paid_key', 'z_param', 'decrypt'）
            expire_hours: 过期时间（小时），如果为None则使用配置的cache_time
        
        Returns:
            是否保存成功
        """
        try:
            # 规范化URL
            normalized_url = video_url.strip().rstrip('/')
            
            # 计算过期时间
            if expire_hours is None:
                expire_hours = self.cache_time // 3600  # 转换为小时
            expire_at = (datetime.now() + timedelta(hours=expire_hours)).isoformat()
            
            # 保存或更新缓存
            self.db.execute_update(
                """
                INSERT OR REPLACE INTO url_parse_cache 
                (video_url, m3u8_url, m3u8_file_path, file_id, parse_method, 
                 updated_at, expire_at, hit_count)
                VALUES (?, ?, ?, ?, ?, datetime('now'), ?, 
                        COALESCE((SELECT hit_count FROM url_parse_cache WHERE video_url = ?), 0))
                """,
                (normalized_url, m3u8_url, m3u8_file_path, file_id, parse_method, 
                 expire_at, normalized_url)
            )
            
            logger.info(f"URL解析缓存已保存: {normalized_url[:100]}... (过期时间: {expire_hours}小时)")
            return True
            
        except Exception as e:
            logger.error(f"保存URL解析缓存失败: {e}", exc_info=True)
            return False
    
    def delete_cache(self, video_url: str) -> bool:
        """
        删除URL解析缓存
        
        Args:
            video_url: 视频URL
        
        Returns:
            是否删除成功
        """
        try:
            normalized_url = video_url.strip().rstrip('/')
            rows = self.db.execute_update(
                "DELETE FROM url_parse_cache WHERE video_url = ?",
                (normalized_url,)
            )
            if rows > 0:
                logger.info(f"URL解析缓存已删除: {normalized_url[:100]}...")
            return rows > 0
        except Exception as e:
            logger.error(f"删除URL解析缓存失败: {e}", exc_info=True)
            return False
    
    def clear_expired(self) -> int:
        """
        清理过期的缓存
        
        Returns:
            清理的记录数
        """
        try:
            rows = self.db.execute_update(
                """
                DELETE FROM url_parse_cache 
                WHERE expire_at IS NOT NULL AND expire_at < datetime('now')
                """
            )
            if rows > 0:
                logger.info(f"清理了 {rows} 条过期的URL解析缓存")
            return rows
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}", exc_info=True)
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        try:
            total = self.db.execute_one(
                "SELECT COUNT(*) as count FROM url_parse_cache"
            )
            expired = self.db.execute_one(
                """
                SELECT COUNT(*) as count FROM url_parse_cache 
                WHERE expire_at IS NOT NULL AND expire_at < datetime('now')
                """
            )
            total_hits = self.db.execute_one(
                "SELECT SUM(hit_count) as total FROM url_parse_cache"
            )
            
            return {
                'total': total['count'] if total else 0,
                'expired': expired['count'] if expired else 0,
                'total_hits': total_hits['total'] if total_hits and total_hits['total'] else 0
            }
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}", exc_info=True)
            return {'total': 0, 'expired': 0, 'total_hits': 0}

    def purge_missing_m3u8_files(self) -> int:
        """
        清理那些指向不存在 m3u8_file_path 的缓存记录（避免返回“坏缓存”）
        
        Returns:
            清理的记录数
        """
        try:
            rows = self.db.execute_query(
                """
                SELECT video_url, m3u8_file_path
                FROM url_parse_cache
                WHERE m3u8_file_path IS NOT NULL AND m3u8_file_path != ''
                """
            )
            
            removed = 0
            for r in rows:
                video_url = r.get("video_url")
                file_path = r.get("m3u8_file_path")
                if not file_path:
                    continue
                if not os.path.exists(file_path):
                    if video_url:
                        if self.delete_cache(video_url):
                            removed += 1
            
            if removed > 0:
                logger.info(f"已清理 {removed} 条无效URL解析缓存（m3u8文件不存在）")
            return removed
        except Exception as e:
            logger.error(f"清理无效URL解析缓存失败: {e}", exc_info=True)
            return 0

    def clear_all(self) -> int:
        """
        清空所有URL解析缓存（强制全量清理）
        
        Returns:
            清理的记录数
        """
        try:
            rows = self.db.execute_update("DELETE FROM url_parse_cache")
            if rows > 0:
                logger.info(f"已清空URL解析缓存表: {rows} 条")
            else:
                logger.info("URL解析缓存表为空，无需清理")
            return rows if rows and rows > 0 else 0
        except Exception as e:
            logger.error(f"清空URL解析缓存失败: {e}", exc_info=True)
            return 0


# 全局URL解析缓存实例
url_parse_cache = URLParseCache()
