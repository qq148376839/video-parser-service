"""
资源检索解析器模块
支持关键词搜索，批量解析多个视频平台的资源
"""
import requests
import json
import re
from typing import List, Dict, Optional, Set
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.logger import logger
from utils.config_loader import config_loader
from .paid_key_parser import PaidKeyParser
from .z_param_parser import ZParamParser
from .decrypt_parser import DecryptParser


class SearchParser:
    """资源检索解析器"""
    
    def __init__(self):
        """初始化资源检索解析器"""
        self.paid_key_parser = PaidKeyParser()
        self.z_param_parser = ZParamParser()
        self.decrypt_parser = DecryptParser()
        logger.info("资源检索解析器初始化完成")
    
    def search_api_sites(self, keyword: str) -> List[Dict]:
        """
        并发调用所有API站点搜索资源
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            所有API站点返回的资源列表
        """
        api_sites = config_loader.get_api_site_list()
        all_results = []
        
        def fetch_site(site: Dict) -> Optional[Dict]:
            """获取单个站点的搜索结果（优化：快速失败，减少等待时间）"""
            try:
                api_url = site['api'].strip()  # 去除可能的空格
                
                # 验证API URL格式
                if not api_url or not api_url.startswith(('http://', 'https://')):
                    logger.warning(f"站点 [{site['name']}] API URL格式无效: {api_url}")
                    return None
                
                # 确保URL格式正确（去除末尾的斜杠，如果有）
                if api_url.endswith('/'):
                    api_url = api_url[:-1]
                
                search_url = f"{api_url}/?ac=videolist&wd={quote(keyword)}"
                
                logger.info(f"搜索站点 [{site['name']}]: {search_url}")
                
                # 优化：减少超时时间从10秒到5秒，提高响应速度
                # 使用更短的连接超时和读取超时
                response = requests.get(search_url, timeout=(3, 5))  # (连接超时3秒, 读取超时5秒)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data.get('code') == 1 and data.get('list'):
                            logger.info(f"站点 [{site['name']}] 返回 {len(data['list'])} 条结果")
                            return {
                                'site': site['name'],
                                'data': data
                            }
                        else:
                            logger.debug(f"站点 [{site['name']}] 无结果 (code: {data.get('code')}, list长度: {len(data.get('list', []))})")
                    except json.JSONDecodeError as e:
                        logger.error(f"站点 [{site['name']}] 响应JSON解析失败: {e}")
                        logger.debug(f"响应内容: {response.text[:200]}")
                else:
                    logger.warning(f"站点 [{site['name']}] 请求失败: {response.status_code}")
                    logger.debug(f"响应内容: {response.text[:200]}")
            except requests.Timeout:
                logger.warning(f"站点 [{site['name']}] 请求超时（5秒）")
            except requests.RequestException as e:
                logger.warning(f"站点 [{site['name']}] 网络请求异常: {e}")
            except Exception as e:
                logger.error(f"站点 [{site['name']}] 搜索异常: {e}")
            return None
        
        # 并发请求所有站点（优化：增加并发数，提高搜索速度）
        with ThreadPoolExecutor(max_workers=min(len(api_sites), 10)) as executor:
            futures = {executor.submit(fetch_site, site): site for site in api_sites}
            
            # 使用as_completed获取结果，不等待所有请求完成
            for future in as_completed(futures):
                try:
                    # 设置超时，避免长时间等待（6秒，略大于请求超时时间）
                    result = future.result(timeout=6)
                    if result:
                        all_results.append(result)
                except TimeoutError:
                    site = futures[future]
                    logger.debug(f"站点 [{site['name']}] 请求超时（6秒）")
                except Exception as e:
                    site = futures[future]
                    logger.debug(f"站点 [{site['name']}] 请求异常: {e}")
        
        return all_results
    
    def merge_results(self, all_results: List[Dict]) -> List[Dict]:
        """
        合并和去重搜索结果
        
        Args:
            all_results: 所有API站点返回的结果
        
        Returns:
            合并去重后的资源列表
        """
        # 按vod_name去重
        name_map: Dict[str, Dict] = {}
        
        for result in all_results:
            for item in result['data'].get('list', []):
                vod_name = item.get('vod_name', '')
                if not vod_name:
                    continue
                
                if vod_name not in name_map:
                    name_map[vod_name] = item.copy()
                else:
                    # 合并vod_play_url（按平台去重）
                    existing_item = name_map[vod_name]
                    existing_urls = self.parse_play_urls(existing_item.get('vod_play_url', ''))
                    new_urls = self.parse_play_urls(item.get('vod_play_url', ''))
                    
                    # 合并URL，按平台去重
                    merged_urls = self.merge_play_urls(existing_urls, new_urls)
                    existing_item['vod_play_url'] = self.format_play_urls(merged_urls)
                    
                    # 合并其他字段（保留更完整的信息）
                    if not existing_item.get('vod_pic') and item.get('vod_pic'):
                        existing_item['vod_pic'] = item['vod_pic']
                    if not existing_item.get('vod_content') and item.get('vod_content'):
                        existing_item['vod_content'] = item['vod_content']
        
        return list(name_map.values())
    
    def parse_play_urls(self, play_url_str: str) -> Dict[str, List[str]]:
        """
        解析vod_play_url字符串，提取平台和URL列表（支持多集）
        
        支持格式：
        1. 标准格式：正片$url1$$$正片$url2
        2. 多集格式（单个$分隔）：正片$url1$url2$url3
        3. 带集标识符格式：正片$1$url1#2$url2#3$url3 或 正片$第1话$url1#第2话$url2
        
        Args:
            play_url_str: vod_play_url字符串
        
        Returns:
            字典，key为平台标识，value为URL列表（或带集标识符的元组列表）
        """
        urls = {}
        if not play_url_str or not play_url_str.strip():
            return urls
        
        # 分割：$$$
        parts = play_url_str.split('$$$')
        for part in parts:
            part = part.strip()
            if not part or '$' not in part:
                continue
            
            # 格式：正片$url 或 平台名$url 或 正片$url1$url2$url3（多集）
            # 或：正片$1$url1#2$url2#3$url3（带集标识符）
            parts_split = part.split('$', 1)  # 只分割第一个$，保留后续部分
            if len(parts_split) < 2:
                continue
            
            label = parts_split[0].strip()
            url_content = parts_split[1].strip()
            
            # 检查是否包含带集标识符的格式：[集数或集名]$[URL]#[集数或集名]$[URL]#...
            # 使用#作为集之间的分隔符
            if '#' in url_content:
                # 带集标识符格式：1$url1#2$url2#3$url3
                episode_pairs = []
                episode_parts = url_content.split('#')
                
                for ep_part in episode_parts:
                    ep_part = ep_part.strip()
                    if not ep_part or '$' not in ep_part:
                        continue
                    
                    # 分割集标识符和URL
                    ep_split = ep_part.split('$', 1)
                    if len(ep_split) == 2:
                        episode_label = ep_split[0].strip()
                        episode_url = ep_split[1].strip()
                        
                        # 验证URL格式
                        if episode_url.startswith(('http://', 'https://')):
                            episode_pairs.append((episode_label, episode_url))
                
                if episode_pairs:
                    # 识别平台（使用第一个URL）
                    first_url = episode_pairs[0][1]
                    platform = self.identify_platform(first_url)
                    if platform:
                        # 存储为元组列表，保留集标识符
                        if platform not in urls:
                            urls[platform] = episode_pairs
                        else:
                            # 合并（去重URL）
                            existing_urls = {url for _, url in urls[platform]}
                            new_pairs = [(label, url) for label, url in episode_pairs if url not in existing_urls]
                            if new_pairs:
                                urls[platform].extend(new_pairs)
                        logger.info(f"检测到多集URL（带集标识符），共 {len(episode_pairs)} 集")
                    continue
            
            # 标准格式：正片$url 或 正片$url1$url2$url3（多集用单个$分隔）
            url_parts = url_content.split('$')
            first_url = url_parts[0].strip() if url_parts else ""
            
            # 验证第一个URL格式
            if not first_url or not first_url.startswith(('http://', 'https://')):
                logger.debug(f"跳过无效URL: {first_url[:50]}...")
                continue
            
            # 识别平台
            platform = self.identify_platform(first_url)
            if not platform:
                logger.debug(f"无法识别平台，跳过URL: {first_url[:50]}...")
                continue
            
            # 检查URL是否包含多个集（用$分隔的完整URL）
            episode_urls = []
            
            # 合并所有URL部分（可能第一个URL本身就包含多个集）
            combined_url = '$'.join(url_parts)
            
            # 使用正则表达式分割多集URL：查找$后面跟着http://或https://的位置
            url_pattern = r'\$https?://'
            url_matches = list(re.finditer(url_pattern, combined_url))
            
            if len(url_matches) > 0:
                # 找到多个URL，说明是多集
                start_pos = 0
                for match in url_matches:
                    if start_pos < match.start():
                        episode_url = combined_url[start_pos:match.start()].strip()
                        if episode_url.startswith(('http://', 'https://')):
                            episode_urls.append(episode_url)
                    start_pos = match.start() + 1
                
                # 添加最后一个URL
                if start_pos < len(combined_url):
                    episode_url = combined_url[start_pos:].strip()
                    if episode_url.startswith(('http://', 'https://')):
                        episode_urls.append(episode_url)
                
                if len(episode_urls) > 1:
                    logger.info(f"检测到多集URL，共 {len(episode_urls)} 集")
            else:
                # 单集URL
                episode_urls = [first_url]
                # 检查后续部分是否也是URL
                for url_part in url_parts[1:]:
                    url_part = url_part.strip()
                    if url_part.startswith(('http://', 'https://')):
                        episode_urls.append(url_part)
            
            if episode_urls:
                if platform not in urls:
                    urls[platform] = episode_urls
                else:
                    # 合并URL列表（去重）
                    existing_urls = set(urls[platform])
                    new_urls = [url for url in episode_urls if url not in existing_urls]
                    if new_urls:
                        urls[platform].extend(new_urls)
                        logger.debug(f"平台 [{platform}] 合并了 {len(new_urls)} 个新URL")
        
        return urls
    
    def identify_platform(self, url: str) -> Optional[str]:
        """
        识别视频平台
        
        Args:
            url: 视频URL
        
        Returns:
            平台标识（bilibili、vqq、youku、iqiyi等）
        """
        url_lower = url.lower()
        if 'bilibili.com' in url_lower or 'b23.tv' in url_lower:
            return 'bilibili'
        elif 'v.qq.com' in url_lower:
            return 'vqq'  # 使用vqq而不是qq，与用户需求一致
        elif 'qq.com' in url_lower:
            return 'vqq'
        elif 'youku.com' in url_lower:
            return 'youku'
        elif 'iqiyi.com' in url_lower:
            return 'iqiyi'
        elif 'mgtv.com' in url_lower:
            return 'mgtv'
        elif 'le.com' in url_lower:
            return 'letv'
        else:
            return None  # 不识别平台时返回None，不添加到字典中
    
    def merge_play_urls(self, urls1: Dict[str, List[str]], urls2: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        合并两个URL字典，相同平台合并URL列表
        
        Args:
            urls1: 第一个URL字典
            urls2: 第二个URL字典
        
        Returns:
            合并后的URL字典
        """
        merged = {}
        
        # 处理urls1
        for platform, url_value in urls1.items():
            if isinstance(url_value, list):
                merged[platform] = url_value.copy()
            else:
                merged[platform] = [url_value]
        
        # 合并urls2
        for platform, url_value in urls2.items():
            if isinstance(url_value, list):
                url_list = url_value
            else:
                url_list = [url_value]
            
            if platform not in merged:
                merged[platform] = url_list
            else:
                # 合并URL列表（去重）
                existing_urls = set(merged[platform])
                new_urls = [url for url in url_list if url not in existing_urls]
                if new_urls:
                    merged[platform].extend(new_urls)
        
        return merged
    
    def format_play_urls(self, urls: Dict[str, str]) -> str:
        """
        格式化URL字典为vod_play_url字符串（兼容旧格式）
        
        自动去重：如果多个平台解析出相同的URL，只保留第一个出现的平台
        
        支持带集标识符格式：[集数或集名]$[URL]#[集数或集名]$[URL]#...
        
        Args:
            urls: URL字典，value可以是：
                - 字符串（单集）
                - 列表（多集URL）
                - 元组列表（带集标识符）：[(label1, url1), (label2, url2), ...]
        
        Returns:
            格式化后的字符串
        """
        parts = []
        seen_urls = set()  # 用于去重
        
        for platform, url_value in urls.items():
            # 检查是否是带集标识符的格式（元组列表）
            if isinstance(url_value, list) and url_value and isinstance(url_value[0], tuple):
                # 带集标识符格式：[(label1, url1), (label2, url2), ...]
                unique_pairs = []
                for label, url in url_value:
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        unique_pairs.append((label, url))
                
                if unique_pairs:
                    # 格式：正片$label1$url1#label2$url2#label3$url3
                    episode_strs = [f"{label}${url}" for label, url in unique_pairs]
                    if len(episode_strs) == 1:
                        parts.append(f"正片${episode_strs[0]}")
                    else:
                        episode_str = '#'.join(episode_strs)
                        parts.append(f"正片${episode_str}")
            elif isinstance(url_value, list):
                # 多集URL：正片$url1$url2$url3
                # 对列表中的URL也进行去重
                unique_episodes = []
                for url in url_value:
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        unique_episodes.append(url)
                
                if unique_episodes:
                    if len(unique_episodes) == 1:
                        parts.append(f"正片${unique_episodes[0]}")
                    else:
                        url_str = '$'.join(unique_episodes)
                        parts.append(f"正片${url_str}")
            else:
                # 单集URL：正片$url
                # 如果URL已存在，跳过（去重）
                if url_value and url_value not in seen_urls:
                    seen_urls.add(url_value)
                    parts.append(f"正片${url_value}")
        
        return '$$$'.join(parts)
    
    def _parse_episodes_parallel(self, platform: str, url_list: List[str], 
                                  parser_url: str) -> List[str]:
        """
        并发解析多集，保持顺序
        
        Args:
            platform: 平台标识
            url_list: URL列表
            parser_url: 解析网站URL
        
        Returns:
            解析后的m3u8列表（按原始顺序）
        """
        def parse_single_episode(idx: int, url: str) -> tuple:
            """
            解析单集，返回(索引, m3u8_url)
            
            Args:
                idx: URL在列表中的索引
                url: 视频URL
            
            Returns:
                (索引, m3u8_url) 元组，如果失败则m3u8_url为None
            """
            # 验证URL格式
            if not url or not url.startswith(('http://', 'https://')):
                logger.warning(f"[{platform}] 第{idx+1}集 URL格式无效，跳过: {url[:100]}...")
                return (idx, None)
            
            # 使用原始URL（保留#后面的集数标记）
            clean_url = url
            
            logger.info(f"解析 [{platform}] 第{idx+1}集 URL: {clean_url[:100]}...")
            
            # 优先级1: 2s0解析（带重试机制，最多重试2次）
            m3u8_url = self.paid_key_parser.parse(clean_url, max_retries=2)
            if m3u8_url:
                logger.info(f"[{platform}] 第{idx+1}集 2s0解析成功")
                return (idx, m3u8_url)
            else:
                logger.debug(f"[{platform}] 第{idx+1}集 2s0解析失败（已重试2次），切换到下一个解析器")
            
            # 优先级2: z参数解析
            m3u8_url = self.z_param_parser.parse(clean_url)
            if m3u8_url:
                logger.info(f"[{platform}] 第{idx+1}集 z参数解析成功")
                return (idx, m3u8_url)
            else:
                logger.debug(f"[{platform}] 第{idx+1}集 z参数解析失败，切换到下一个解析器")
            
            # 优先级3: 解密解析
            m3u8_url = self.decrypt_parser.parse(parser_url, clean_url)
            if m3u8_url:
                logger.info(f"[{platform}] 第{idx+1}集 解密解析成功")
                return (idx, m3u8_url)
            
            logger.warning(f"[{platform}] 第{idx+1}集 所有解析方案都失败")
            return (idx, None)
        
        # 并发执行
        results = {}  # {index: m3u8_url}
        
        # 如果只有1集，直接串行解析（避免线程开销）
        if len(url_list) == 1:
            idx, m3u8_url = parse_single_episode(0, url_list[0])
            if m3u8_url:
                results[idx] = m3u8_url
        else:
            # 多集使用线程池并发解析
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(parse_single_episode, idx, url): (idx, url)
                    for idx, url in enumerate(url_list)
                }
                
                for future in as_completed(futures):
                    try:
                        idx, m3u8_url = future.result()
                        if m3u8_url:
                            results[idx] = m3u8_url
                    except Exception as e:
                        idx, _ = futures[future]
                        logger.error(f"[{platform}] 第{idx+1}集 解析异常: {e}")
        
        # 按索引排序，保持原始顺序
        sorted_results = [results[i] for i in sorted(results.keys())]
        return sorted_results
    
    def parse_video_urls(self, play_url_str: str, parser_url: str = "https://jx.789jiexi.com") -> str:
        """
        解析vod_play_url中的所有视频URL，替换为m3u8地址（支持多集，使用多线程并发）
        
        支持带集标识符格式：[集数或集名]$[URL]#[集数或集名]$[URL]#...
        解析后保持原始格式，只替换URL部分
        
        Args:
            play_url_str: vod_play_url字符串
            parser_url: 解析网站URL
        
        Returns:
            解析后的vod_play_url字符串（失败的部分会被删除）
        """
        urls = self.parse_play_urls(play_url_str)
        parsed_urls = {}
        
        for platform, url_list in urls.items():
            if not url_list:
                continue
            
            # 检查是否是带集标识符的格式（元组列表）
            has_episode_labels = False
            if url_list and isinstance(url_list[0], tuple):
                has_episode_labels = True
                # 提取URL列表用于解析
                original_urls = [url for _, url in url_list]
                episode_labels = [label for label, _ in url_list]
            else:
                # 标准格式：url_list可能是列表（多集）或字符串（单集，兼容旧格式）
                if isinstance(url_list, str):
                    url_list = [url_list]
                original_urls = url_list
                episode_labels = None
            
            # 多线程并发解析，保持顺序
            parsed_episodes = self._parse_episodes_parallel(platform, original_urls, parser_url)
            
            if parsed_episodes:
                if has_episode_labels:
                    # 带集标识符格式：保留集标识符，只替换URL
                    parsed_pairs = []
                    for i, m3u8_url in enumerate(parsed_episodes):
                        if i < len(episode_labels) and m3u8_url:
                            parsed_pairs.append((episode_labels[i], m3u8_url))
                    if parsed_pairs:
                        parsed_urls[platform] = parsed_pairs
                        logger.info(f"[{platform}] 共解析成功 {len(parsed_pairs)}/{len(original_urls)} 集（带集标识符）")
                else:
                    # 标准格式
                    if len(parsed_episodes) == 1:
                        # 单集，直接存储字符串（兼容旧格式）
                        parsed_urls[platform] = parsed_episodes[0]
                    else:
                        # 多集，存储列表
                        parsed_urls[platform] = parsed_episodes
                    logger.info(f"[{platform}] 共解析成功 {len(parsed_episodes)}/{len(original_urls)} 集")
            else:
                logger.warning(f"[{platform}] 所有集解析失败，将删除")
        
        return self.format_play_urls(parsed_urls)
    
    def search_and_parse(self, keyword: str, parser_url: str = "https://jx.789jiexi.com") -> Dict:
        """
        搜索资源并解析视频地址
        
        Args:
            keyword: 搜索关键词
            parser_url: 解析网站URL
        
        Returns:
            搜索结果，包含解析后的m3u8地址
        """
        logger.info(f"搜索资源: {keyword}")
        
        # 1. 搜索所有API站点
        all_results = self.search_api_sites(keyword)
        
        if not all_results:
            logger.warning("所有API站点都无结果")
            return {
                "code": 1,
                "msg": "数据列表",
                "page": 1,
                "pagecount": 0,
                "limit": 20,
                "total": 0,
                "list": []
            }
        
        # 2. 合并去重
        merged_list = self.merge_results(all_results)
        logger.info(f"合并后共 {len(merged_list)} 条资源")
        
        # 3. 解析视频地址
        parsed_list = []
        for item in merged_list:
            play_url = item.get('vod_play_url', '')
            if not play_url:
                logger.debug(f"资源 [{item.get('vod_name')}] 没有vod_play_url，跳过")
                continue
            
            # 解析所有视频URL
            parsed_play_url = self.parse_video_urls(play_url, parser_url)
            
            # 如果解析后还有URL，保留该资源
            if parsed_play_url and parsed_play_url.strip():
                item['vod_play_url'] = parsed_play_url
                parsed_list.append(item)
                logger.debug(f"资源 [{item.get('vod_name')}] 解析成功，保留 {len(self.parse_play_urls(parsed_play_url))} 个URL")
            else:
                logger.warning(f"资源 [{item.get('vod_name')}] 所有URL解析失败，已删除")
        
        logger.info(f"解析后剩余 {len(parsed_list)} 条资源")
        
        # 如果所有资源都解析失败，返回空列表
        if not parsed_list:
            logger.warning("所有资源解析失败，返回空列表")
            return {
                "code": 1,
                "msg": "数据列表",
                "page": 1,
                "pagecount": 0,
                "limit": 20,
                "total": 0,
                "list": []
            }
        
        return {
            "code": 1,
            "msg": "数据列表",
            "page": 1,
            "pagecount": 1 if parsed_list else 0,
            "limit": 20,
            "total": len(parsed_list),
            "list": parsed_list
        }

