"""
搜索缓存管理模块
负责搜索结果的缓存读写、过期检查、增量更新等功能
"""
import json
from typing import Optional, Dict, List, Set
from datetime import datetime, timedelta

from utils.logger import logger
from utils.database import get_database
from utils.config_loader import config_loader


class SearchCache:
    """搜索缓存管理类"""
    
    def __init__(self, db_path: str = None, cache_time: int = None):
        """
        初始化搜索缓存管理器
        
        Args:
            db_path: 数据库文件路径
            cache_time: 缓存过期时间（秒），如果为None则从配置文件读取
        """
        self.db = get_database(db_path)
        
        # 获取缓存时间（从配置文件或使用默认值）
        if cache_time is None:
            self.cache_time = config_loader.get_cache_time()  # 默认2小时
        else:
            self.cache_time = cache_time
        
        logger.info(f"搜索缓存管理器初始化完成，缓存时间: {self.cache_time}秒")
    
    def normalize_keyword(self, keyword: str) -> str:
        """
        规范化搜索关键词
        
        Args:
            keyword: 原始关键词
        
        Returns:
            规范化后的关键词（小写，去除首尾空格）
        """
        return keyword.lower().strip()
    
    def get_cache(self, keyword: str) -> Optional[Dict]:
        """
        获取缓存结果
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            缓存结果（字典），如果不存在或已过期返回None
        """
        normalized_keyword = self.normalize_keyword(keyword)
        
        try:
            # 查询缓存
            cache_record = self.db.execute_one(
                """
                SELECT results, updated_at, expire_at, hit_count 
                FROM search_cache 
                WHERE keyword = ?
                """,
                (normalized_keyword,)
            )
            
            if not cache_record:
                logger.debug(f"缓存未命中: {keyword}")
                return None
            
            # 检查是否过期
            if self.is_expired(normalized_keyword, cache_record):
                logger.debug(f"缓存已过期: {keyword}")
                return None
            
            # 更新命中次数
            self.db.execute_update(
                """
                UPDATE search_cache 
                SET hit_count = hit_count + 1 
                WHERE keyword = ?
                """,
                (normalized_keyword,)
            )
            
            # 解析JSON结果
            try:
                results = json.loads(cache_record['results'])
                logger.info(f"缓存命中: {keyword} (命中次数: {cache_record['hit_count'] + 1})")
                return results
            except json.JSONDecodeError as e:
                logger.error(f"解析缓存结果失败: {e}")
                return None
                
        except Exception as e:
            logger.error(f"获取缓存失败: {e}", exc_info=True)
            return None
    
    def set_cache(self, keyword: str, results: Dict) -> bool:
        """
        设置缓存结果
        
        Args:
            keyword: 搜索关键词
            results: 搜索结果（字典）
        
        Returns:
            是否设置成功
        """
        # 搜索结果为空时不缓存
        if not results or not results.get('list'):
            logger.debug(f"搜索结果为空，不缓存: {keyword}")
            return False
        
        normalized_keyword = self.normalize_keyword(keyword)
        
        try:
            # 序列化结果
            results_json = json.dumps(results, ensure_ascii=False)
            
            # 计算过期时间
            expire_at = (datetime.now() + timedelta(seconds=self.cache_time)).isoformat()
            
            # 插入或更新缓存
            self.db.execute_update(
                """
                INSERT OR REPLACE INTO search_cache 
                (keyword, results, updated_at, expire_at, hit_count)
                VALUES (?, ?, ?, ?, 
                    COALESCE((SELECT hit_count FROM search_cache WHERE keyword = ?), 0))
                """,
                (
                    normalized_keyword,
                    results_json,
                    datetime.now().isoformat(),
                    expire_at,
                    normalized_keyword  # 用于COALESCE查询
                )
            )
            
            logger.info(f"缓存已保存: {keyword}")
            return True
            
        except Exception as e:
            logger.error(f"保存缓存失败: {e}", exc_info=True)
            return False
    
    def is_expired(self, keyword: str, cache_record: Dict = None) -> bool:
        """
        检查缓存是否过期
        
        Args:
            keyword: 搜索关键词
            cache_record: 缓存记录（如果为None则从数据库查询）
        
        Returns:
            是否过期
        """
        if cache_record is None:
            cache_record = self.db.execute_one(
                "SELECT updated_at, expire_at FROM search_cache WHERE keyword = ?",
                (self.normalize_keyword(keyword),)
            )
            if not cache_record:
                return True
        
        # 优先使用expire_at
        if cache_record.get('expire_at'):
            try:
                expire_at = datetime.fromisoformat(cache_record['expire_at'])
                return datetime.now() > expire_at
            except Exception as e:
                logger.warning(f"解析过期时间失败: {e}")
        
        # 回退到基于updated_at和cache_time的判断
        updated_at_str = cache_record.get('updated_at')
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                age = datetime.now() - updated_at
                return age.total_seconds() > self.cache_time
            except Exception as e:
                logger.warning(f"解析更新时间失败: {e}")
        
        return True
    
    def clear_cache(self, keyword: str) -> bool:
        """
        清除指定关键词的缓存
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            是否清除成功
        """
        normalized_keyword = self.normalize_keyword(keyword)
        
        try:
            count = self.db.execute_update(
                "DELETE FROM search_cache WHERE keyword = ?",
                (normalized_keyword,)
            )
            if count > 0:
                logger.info(f"已清除缓存: {keyword}")
            return True
        except Exception as e:
            logger.error(f"清除缓存失败: {e}", exc_info=True)
            return False
    
    def clear_expired_cache(self) -> int:
        """
        清除所有过期缓存
        
        Returns:
            清除的缓存数量
        """
        try:
            now = datetime.now().isoformat()
            
            # 删除过期时间已过的缓存
            count1 = self.db.execute_update(
                "DELETE FROM search_cache WHERE expire_at IS NOT NULL AND expire_at < ?",
                (now,)
            )
            
            # 删除基于updated_at过期的缓存
            # 计算过期时间点
            expire_threshold = (datetime.now() - timedelta(seconds=self.cache_time)).isoformat()
            count2 = self.db.execute_update(
                "DELETE FROM search_cache WHERE expire_at IS NULL AND updated_at < ?",
                (expire_threshold,)
            )
            
            total_count = count1 + count2
            if total_count > 0:
                logger.info(f"已清除 {total_count} 条过期缓存")
            
            return total_count
            
        except Exception as e:
            logger.error(f"清除过期缓存失败: {e}", exc_info=True)
            return 0
    
    def get_cache_stats(self) -> Dict:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        try:
            total = self.db.execute_one("SELECT COUNT(*) as count FROM search_cache")
            total_count = total['count'] if total else 0
            
            expired = self.db.execute_one(
                """
                SELECT COUNT(*) as count FROM search_cache 
                WHERE expire_at IS NOT NULL AND expire_at < ?
                """,
                (datetime.now().isoformat(),)
            )
            expired_count = expired['count'] if expired else 0
            
            total_hits = self.db.execute_one(
                "SELECT SUM(hit_count) as total FROM search_cache"
            )
            total_hits_count = total_hits['total'] if total_hits and total_hits['total'] else 0
            
            return {
                'total': total_count,
                'expired': expired_count,
                'valid': total_count - expired_count,
                'total_hits': total_hits_count,
                'cache_time': self.cache_time
            }
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}", exc_info=True)
            return {}
    
    def compare_and_get_new_episodes(self, cached_item: Dict, new_item: Dict) -> Dict:
        """
        比较缓存项和新搜索项，识别新增的集数
        
        注意：缓存中的URL是m3u8 URL，新搜索的URL是原始视频URL，无法直接比较。
        因此通过比较集数数量来判断是否有新增。
        
        Args:
            cached_item: 缓存中的视频项
            new_item: 新搜索到的视频项
        
        Returns:
            包含新增集数的字典，格式: {'has_new': bool, 'new_urls': List[str], 'new_count': int}
        """
        cached_urls = self._extract_urls_from_play_url(cached_item.get('vod_play_url', ''))
        new_urls = self._extract_urls_from_play_url(new_item.get('vod_play_url', ''))
        
        cached_count = len(cached_urls)
        new_total_count = len(new_urls)
        
        # 通过比较集数数量来判断是否有新增
        if new_total_count > cached_count:
            # 有新增集数，提取新增部分的URL
            new_url_list = new_urls[cached_count:]
            return {
                'has_new': True,
                'new_urls': new_url_list,
                'new_count': len(new_url_list),
                'cached_count': cached_count,
                'new_total_count': new_total_count
            }
        else:
            # 无新增
            return {
                'has_new': False,
                'new_urls': [],
                'new_count': 0,
                'cached_count': cached_count,
                'new_total_count': new_total_count
            }
    
    def _extract_urls_from_play_url(self, play_url_str: str) -> List[str]:
        """
        从vod_play_url字符串中提取所有URL
        
        Args:
            play_url_str: vod_play_url字符串
        
        Returns:
            URL列表
        """
        urls = []
        if not play_url_str:
            return urls
        
        # 分割：$$$
        parts = play_url_str.split('$$$')
        for part in parts:
            part = part.strip()
            if not part or '$' not in part:
                continue
            
            # 分割第一个$，获取URL部分
            url_part = part.split('$', 1)[1] if '$' in part else part
            
            # 处理带集标识符格式：1$url1#2$url2#3$url3
            if '#' in url_part:
                episode_parts = url_part.split('#')
                for ep_part in episode_parts:
                    ep_part = ep_part.strip()
                    if '$' in ep_part:
                        url = ep_part.split('$', 1)[1].strip()
                        if url.startswith(('http://', 'https://')):
                            urls.append(url)
            else:
                # 标准格式：可能包含多个$分隔的URL
                url_parts = url_part.split('$')
                for url in url_parts:
                    url = url.strip()
                    if url.startswith(('http://', 'https://')):
                        urls.append(url)
        
        return urls
    
    def merge_results(self, cached_results: Dict, new_results: Dict) -> Dict:
        """
        合并缓存结果和新搜索结果
        
        Args:
            cached_results: 缓存中的搜索结果
            new_results: 新搜索到的结果
        
        Returns:
            合并后的结果
        """
        # 创建缓存项的映射（按vod_name）
        cached_map = {}
        for item in cached_results.get('list', []):
            vod_name = item.get('vod_name')
            if vod_name:
                cached_map[vod_name] = item
        
        # 合并逻辑
        merged_list = []
        updated_count = 0
        
        for new_item in new_results.get('list', []):
            vod_name = new_item.get('vod_name')
            if not vod_name:
                continue
            
            if vod_name in cached_map:
                # 已存在的项，检查是否有新增集数
                cached_item = cached_map[vod_name]
                comparison = self.compare_and_get_new_episodes(cached_item, new_item)
                
                if comparison['has_new']:
                    # 有新增集数，需要合并URL
                    # 这里只标记，实际解析在search_parser中完成
                    merged_item = cached_item.copy()
                    # 保留新搜索的vod_play_url（包含所有集数），后续会解析新增部分
                    merged_item['vod_play_url'] = new_item['vod_play_url']
                    merged_list.append(merged_item)
                    updated_count += 1
                    logger.info(f"发现新增集数: {vod_name} (+{comparison['new_count']}集)")
                else:
                    # 无新增，使用缓存项
                    merged_list.append(cached_item)
            else:
                # 新项，直接添加
                merged_list.append(new_item)
        
        # 构建合并后的结果
        merged_results = {
            'code': new_results.get('code', 1),
            'msg': new_results.get('msg', '数据列表'),
            'page': new_results.get('page', 1),
            'pagecount': new_results.get('pagecount', 1),
            'limit': new_results.get('limit', 20),
            'total': len(merged_list),
            'list': merged_list
        }
        
        if updated_count > 0:
            logger.info(f"合并完成: 共 {len(merged_list)} 项，其中 {updated_count} 项有新增集数")
        
        return merged_results


# 全局缓存实例（延迟初始化）
_cache_instance: Optional[SearchCache] = None


def get_search_cache(db_path: str = None, cache_time: int = None) -> SearchCache:
    """
    获取全局搜索缓存实例（单例模式）
    
    Args:
        db_path: 数据库文件路径（仅在首次调用时有效）
        cache_time: 缓存时间（仅在首次调用时有效）
    
    Returns:
        SearchCache实例
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SearchCache(db_path, cache_time)
    return _cache_instance
