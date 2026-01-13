"""
z参数解析器模块
使用z参数方式解析视频（主要方案）
"""
import requests
import json
import re
import asyncio
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Tuple
from utils.logger import logger
from utils.z_param_manager import z_param_manager
from utils.m3u8_cleaner import M3U8Cleaner
from utils.m3u8_key_rewriter import rewrite_m3u8_key_uris

# 项目根目录
project_root = Path(__file__).parent.parent

# 创建线程池用于运行Playwright（避免asyncio冲突）
_playwright_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")


class ZParamParser:
    """z参数解析器（主要方案）"""
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        初始化z参数解析器
        
        Args:
            api_base_url: API服务的基础URL，用于生成m3u8文件的访问链接
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Referer': 'https://m1-z2.cloud.nnpp.vip:2223/',
            'Origin': 'https://m1-z2.cloud.nnpp.vip:2223',
        })
        self.api_base_url = api_base_url.rstrip('/')
        # 存储m3u8文件路径的映射 {file_id: file_path}
        self.m3u8_files = {}
        logger.info("z参数解析器初始化完成")
    
    def construct_api_url(self, video_url: str) -> Optional[str]:
        """
        构造API URL
        
        Args:
            video_url: 视频URL
        
        Returns:
            API URL，如果失败返回None
        """
        z_param = z_param_manager.get_z_param()
        s1ig_param = z_param_manager.get_s1ig_param()
        g_param = z_param_manager.get_g_param()
        
        if not z_param:
            logger.warning("z参数不存在，无法构造API URL")
            return None
        
        api_url = f"https://m1-a1.cloud.nnpp.vip:2223/api/v/?z={z_param}&jx={video_url}&s1ig={s1ig_param}&g={g_param}"
        logger.info(f"z参数解析器: 构造API URL: {api_url[:100]}...")
        return api_url
    
    def call_api(self, api_url: str) -> Tuple[Optional[Dict], bool]:
        """
        调用API获取视频信息
        
        Args:
            api_url: API URL
        
        Returns:
            (API响应数据, 是否是z参数过期) 元组
            如果失败且是z参数过期，返回(None, True)
            如果失败但不是z参数过期，返回(None, False)
            如果成功，返回(响应数据, False)
        """
        try:
            # 移除Accept-Encoding避免压缩问题
            headers = self.session.headers.copy()
            if 'Accept-Encoding' in headers:
                del headers['Accept-Encoding']
            
            response = self.session.get(api_url, headers=headers, timeout=30, allow_redirects=True)
            
            if response.status_code != 200:
                logger.warning(f"API返回非200状态码: {response.status_code}")
                return None, False
            
            # 处理响应内容
            content = response.text
            
            # 检查是否是错误信息（z参数过期）
            if '联系QQ' in content or '获取json版api地址' in content:
                logger.warning("API返回错误信息，z参数可能已过期")
                return None, True
            
            # 尝试解析JSON
            try:
                json_data = json.loads(content)
                return json_data, False
            except json.JSONDecodeError:
                # 尝试从响应中提取m3u8链接
                m3u8_patterns = [
                    r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                    r'["\']([^"\']+\.m3u8[^"\']*)["\']',
                ]
                
                for pattern in m3u8_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        url = match if isinstance(match, str) else match[0] if match else None
                        if url and url.startswith('http'):
                            logger.info(f"从响应中提取到m3u8链接: {url[:100]}...")
                            return {'m3u8_url': url}, False
                
                logger.warning("无法解析API响应")
                return None, False
                
        except Exception as e:
            logger.error(f"调用API失败: {e}")
            return None, False
    
    def extract_m3u8(self, api_response: Dict) -> Optional[str]:
        """
        从API响应中提取m3u8链接
        
        Args:
            api_response: API响应数据
        
        Returns:
            m3u8链接，如果失败返回None
        """
        # 如果响应中直接包含m3u8_url
        if 'm3u8_url' in api_response:
            return api_response['m3u8_url']
        
        # 递归查找m3u8链接
        def find_m3u8(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    result = find_m3u8(value, f"{path}.{key}")
                    if result:
                        return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = find_m3u8(item, f"{path}[{i}]")
                    if result:
                        return result
            elif isinstance(obj, str) and '.m3u8' in obj and obj.startswith('http'):
                return obj
            return None
        
        m3u8_url = find_m3u8(api_response)
        return m3u8_url
    
    def parse(self, video_url: str) -> Optional[str]:
        """
        解析视频URL，返回m3u8链接
        
        Args:
            video_url: 视频URL（如果包含$分隔的多集URL，只解析第一个）
        
        Returns:
            m3u8链接，如果失败返回None
        """
        import time
        start_time = time.time()
        
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
            
            # 验证URL格式
            if not video_url or not video_url.startswith(('http://', 'https://')):
                logger.error(f"无效的视频URL格式: {video_url}")
                return None
            
            logger.info(f"使用z参数方案解析: {video_url}")
            
            # 检查z参数是否过期或不存在
            z_param_check_start = time.time()
            if z_param_manager.is_expired() or not z_param_manager.get_z_param():
                logger.info("z参数已过期或不存在，尝试更新...")
                # 先尝试HTTP方式（快速）
                http_update_start = time.time()
                new_z = z_param_manager.update_with_http(video_url)
                http_update_time = time.time() - http_update_start
                logger.info(f"z参数解析器: HTTP方式更新耗时: {http_update_time:.2f}秒")
                
                # 如果HTTP方式失败，尝试Playwright方式（需要浏览器）
                if not new_z:
                    logger.info("HTTP方式失败，尝试Playwright方式...")
                    playwright_start = time.time()
                    # 始终在线程池中运行Playwright，避免asyncio冲突
                    # 因为即使parse()在单独线程中，Playwright仍可能检测到asyncio事件循环
                    try:
                        future = _playwright_executor.submit(z_param_manager.update_with_playwright, video_url)
                        new_z = future.result(timeout=60)  # 最多等待60秒
                        playwright_time = time.time() - playwright_start
                        logger.info(f"z参数解析器: Playwright方式更新耗时: {playwright_time:.2f}秒")
                    except Exception as e:
                        logger.error(f"Playwright线程执行失败: {e}", exc_info=True)
                        new_z = None
                
                if not new_z:
                    logger.warning("z参数更新失败，将尝试使用当前参数（如果存在）")
            
            z_param_check_time = time.time() - z_param_check_start
            if z_param_check_time > 0.1:
                logger.info(f"z参数解析器: z参数检查耗时: {z_param_check_time:.2f}秒")
            
            # 构造API URL
            api_url = self.construct_api_url(video_url)
            if not api_url:
                logger.error("无法构造API URL（z参数不存在）")
                return None
            
            # 调用API
            api_call_start = time.time()
            api_response, is_expired = self.call_api(api_url)
            api_call_time = time.time() - api_call_start
            logger.info(f"z参数解析器: API调用耗时: {api_call_time:.2f}秒")
            if not api_response:
                # 如果检测到z参数过期，尝试更新并重试一次
                if is_expired:
                    logger.info("检测到z参数已过期，尝试更新并重试...")
                    # 先尝试HTTP方式（快速）
                    new_z = z_param_manager.update_with_http(video_url)
                    # 如果HTTP方式失败，尝试Playwright方式（需要浏览器）
                    if not new_z:
                        logger.info("HTTP方式失败，尝试Playwright方式...")
                        try:
                            future = _playwright_executor.submit(z_param_manager.update_with_playwright, video_url)
                            new_z = future.result(timeout=60)  # 最多等待60秒
                        except Exception as e:
                            logger.error(f"Playwright线程执行失败: {e}", exc_info=True)
                            new_z = None
                    
                    if new_z:
                        logger.info("z参数更新成功，重新调用API...")
                        # 重新构造API URL
                        api_url = self.construct_api_url(video_url)
                        if api_url:
                            # 重新调用API
                            retry_api_start = time.time()
                            api_response, is_expired_retry = self.call_api(api_url)
                            retry_api_time = time.time() - retry_api_start
                            logger.info(f"z参数解析器: 重试API调用耗时: {retry_api_time:.2f}秒")
                            if not api_response:
                                if is_expired_retry:
                                    logger.warning("z参数更新后API仍然返回过期错误")
                                else:
                                    logger.warning("z参数更新后API调用仍然失败")
                                return None
                        else:
                            logger.error("z参数更新后无法构造API URL")
                            return None
                    else:
                        logger.warning("z参数更新失败，API调用失败")
                        return None
                else:
                    logger.warning("API调用失败（非z参数过期原因）")
                    return None
            
            # 提取m3u8链接
            extract_start = time.time()
            m3u8_url = self.extract_m3u8(api_response)
            extract_time = time.time() - extract_start
            if extract_time > 0.1:
                logger.info(f"z参数解析器: 提取m3u8链接耗时: {extract_time:.2f}秒")
            
            if m3u8_url:
                logger.info(f"z参数方案解析成功: {m3u8_url[:100]}...")
                
                # 下载并清理m3u8文件
                download_start = time.time()
                cleaned_m3u8_url = self._download_and_clean_m3u8(m3u8_url)
                download_time = time.time() - download_start
                logger.info(f"z参数解析器: 下载并清理m3u8文件耗时: {download_time:.2f}秒")
                if cleaned_m3u8_url:
                    return cleaned_m3u8_url
                else:
                    # 如果下载失败，返回原始URL
                    return m3u8_url
            else:
                logger.warning("未能从API响应中提取m3u8链接")
                total_time = time.time() - start_time
                logger.info(f"z参数解析器: 总耗时: {total_time:.2f}秒")
                return None
                
        except Exception as e:
            logger.error(f"z参数方案解析异常: {e}")
            total_time = time.time() - start_time
            logger.info(f"z参数解析器: 总耗时: {total_time:.2f}秒")
            return None
        finally:
            total_time = time.time() - start_time
            if total_time > 1.0:  # 只记录超过1秒的耗时
                logger.info(f"z参数解析器: 总耗时: {total_time:.2f}秒")
    
    def _generate_file_id(self, m3u8_url: str) -> str:
        """
        生成文件ID（基于m3u8 URL的hash）
        注意：文件ID需要与文件名中的hash部分匹配
        """
        import hashlib
        # 从URL提取hash（如果存在）
        hash_match = re.search(r'/Cache/[^/]+/([a-f0-9]+)\.m3u8', m3u8_url)
        if hash_match:
            # 使用URL中的hash（32位十六进制）
            return hash_match.group(1)[:16]  # 取前16位
        else:
            # 如果没有hash，使用MD5
            hash_obj = hashlib.md5(m3u8_url.encode('utf-8'))
            return hash_obj.hexdigest()[:16]
    
    def _convert_relative_paths_to_absolute(self, m3u8_content: str, base_url: str) -> str:
        """
        将m3u8内容中的相对路径转换为绝对URL
        
        Args:
            m3u8_content: m3u8文件内容
            base_url: 用于转换相对路径的基础URL
        
        Returns:
            转换后的m3u8内容
        """
        from urllib.parse import urljoin
        
        lines = m3u8_content.split('\n')
        converted_lines = []
        converted_count = 0
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # 处理#EXT-X-KEY标签中的URI属性
            # 格式: #EXT-X-KEY:METHOD=AES-128,URI="/path/to/key.key",IV=...
            if line_stripped.startswith('#EXT-X-KEY'):
                # 匹配URI="..."或URI='...'中的相对路径
                uri_pattern = r'URI=["\']([^"\']+)["\']'
                uri_match = re.search(uri_pattern, line)
                if uri_match:
                    uri_value = uri_match.group(1)
                    # 如果是相对路径（不是http://或https://开头，且不是//开头）
                    if (not uri_value.startswith(('http://', 'https://')) and 
                        not uri_value.startswith('//')):
                        absolute_uri = urljoin(base_url, uri_value)
                        # 保持原有的引号类型
                        quote_char = '"' if '"' in uri_match.group(0) else "'"
                        line = re.sub(uri_pattern, f'URI={quote_char}{absolute_uri}{quote_char}', line)
                        converted_count += 1
                        logger.debug(f"转换#EXT-X-KEY URI: {uri_value} -> {absolute_uri}")
            
            # 处理#EXTINF后面的ts文件路径（相对路径）
            # 这些路径通常单独成行，不以#开头，且以/开头但不是//开头
            elif line_stripped and not line_stripped.startswith('#'):
                # 检查是否是相对路径（以/开头但不是//开头，且不是http://或https://）
                if (line_stripped.startswith('/') and 
                    not line_stripped.startswith('//') and 
                    not line_stripped.startswith(('http://', 'https://'))):
                    absolute_url = urljoin(base_url, line_stripped)
                    # 保持原有的行格式（保留原始行的尾随空格等）
                    line = line.replace(line_stripped, absolute_url)
                    converted_count += 1
                    logger.debug(f"转换ts文件路径: {line_stripped} -> {absolute_url}")
            
            converted_lines.append(line)
        
        if converted_count > 0:
            logger.info(f"z参数解析器: 已将 {converted_count} 个相对路径转换为绝对URL")
        
        return '\n'.join(converted_lines) if converted_lines else m3u8_content
    
    def _download_and_clean_m3u8(self, m3u8_url: str) -> Optional[str]:
        """
        下载m3u8文件并清理，返回API接口URL
        
        如果相同hash的文件已存在，直接返回现有文件的API接口URL，避免重复下载
        
        支持master playlist重定向：如果下载的m3u8文件是master playlist（包含#EXT-X-STREAM-INF），
        会自动提取其中的相对路径并下载最终的m3u8文件。
        
        Args:
            m3u8_url: m3u8 URL
        
        Returns:
            API接口URL（如果成功），否则返回None
        """
        from urllib.parse import urljoin, urlparse
        
        # 保存到缓存目录
        cache_dir = project_root / "data" / "m3u8_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 从URL提取hash
        hash_match = re.search(r'/Cache/[^/]+/([a-f0-9]+)\.m3u8', m3u8_url)
        
        # 生成文件ID（基于原始URL）
        file_id = self._generate_file_id(m3u8_url)
        
        # 检查是否已有相同hash的文件存在
        if hash_match:
            hash_value = hash_match.group(1)
            # 查找所有以该hash开头的文件
            existing_files = list(cache_dir.glob(f"m3u8_{hash_value}_*.m3u8"))
            if existing_files:
                # 使用最新的文件（按修改时间）
                latest_file = max(existing_files, key=lambda p: p.stat().st_mtime)
                logger.info(f"z参数解析器: 发现已存在的m3u8文件（hash={hash_value}），使用缓存: {latest_file}")
                # 存储文件映射
                self.m3u8_files[file_id] = str(latest_file)
                # 返回API接口URL
                return f"{self.api_base_url}/api/v1/m3u8/{file_id}"
        
        try:
            import time
            download_start = time.time()
            # 下载m3u8文件
            response = self.session.get(m3u8_url, timeout=30)
            response.raise_for_status()
            m3u8_content = response.text
            download_time = time.time() - download_start
            logger.debug(f"z参数解析器: 下载初始m3u8文件耗时: {download_time:.2f}秒")
            
            # 保存最终的m3u8 URL（用于相对路径转换）
            final_m3u8_url_for_base = m3u8_url
            
            # 检查是否是master playlist（包含#EXT-X-STREAM-INF）
            master_playlist_start = time.time()
            if '#EXT-X-STREAM-INF' in m3u8_content:
                logger.info(f"z参数解析器: 检测到master playlist，提取最终m3u8地址...")
                
                # 解析master playlist，提取相对路径
                lines = m3u8_content.split('\n')
                final_m3u8_path = None
                
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    # 查找#EXT-X-STREAM-INF后面的URL行
                    if line_stripped.startswith('#EXT-X-STREAM-INF'):
                        # 下一行应该是URL（相对路径或绝对路径）
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            if next_line and not next_line.startswith('#'):
                                final_m3u8_path = next_line
                                break
                
                if final_m3u8_path:
                    # 如果是相对路径，转换为绝对URL
                    if not final_m3u8_path.startswith(('http://', 'https://')):
                        # 基于原始m3u8_url构建绝对URL（urljoin会自动处理相对路径）
                        final_m3u8_url = urljoin(m3u8_url, final_m3u8_path)
                        logger.info(f"z参数解析器: 将相对路径转换为绝对URL: {final_m3u8_url}")
                    else:
                        final_m3u8_url = final_m3u8_path
                    
                    # 更新用于相对路径转换的base URL
                    final_m3u8_url_for_base = final_m3u8_url
                    
                    # 递归下载最终的m3u8文件（使用最终的URL）
                    # 注意：这里需要更新file_id和hash_match，因为最终的URL可能不同
                    final_hash_match = re.search(r'/Cache/[^/]+/([a-f0-9]+)\.m3u8', final_m3u8_url)
                    if final_hash_match:
                        # 使用最终URL的hash
                        final_hash_value = final_hash_match.group(1)
                        existing_files = list(cache_dir.glob(f"m3u8_{final_hash_value}_*.m3u8"))
                        if existing_files:
                            latest_file = max(existing_files, key=lambda p: p.stat().st_mtime)
                            logger.info(f"z参数解析器: 发现已存在的最终m3u8文件（hash={final_hash_value}），使用缓存: {latest_file}")
                            self.m3u8_files[file_id] = str(latest_file)
                            return f"{self.api_base_url}/api/v1/m3u8/{file_id}"
                    
                    # 下载最终的m3u8文件
                    logger.info(f"z参数解析器: 下载最终的m3u8文件: {final_m3u8_url[:100]}...")
                    final_download_start = time.time()
                    final_response = self.session.get(final_m3u8_url, timeout=30)
                    final_response.raise_for_status()
                    m3u8_content = final_response.text
                    final_download_time = time.time() - final_download_start
                    logger.debug(f"z参数解析器: 下载最终m3u8文件耗时: {final_download_time:.2f}秒")
                else:
                    logger.warning(f"z参数解析器: 无法从master playlist中提取m3u8路径")
            
            master_playlist_time = time.time() - master_playlist_start
            if master_playlist_time > 0.1:
                logger.debug(f"z参数解析器: master playlist处理耗时: {master_playlist_time:.2f}秒")
            
            # 将m3u8内容中的相对路径转换为绝对URL
            convert_start = time.time()
            m3u8_content = self._convert_relative_paths_to_absolute(m3u8_content, final_m3u8_url_for_base)
            convert_time = time.time() - convert_start
            if convert_time > 0.1:
                logger.debug(f"z参数解析器: 相对路径转换耗时: {convert_time:.2f}秒")
            
            # 清理m3u8内容
            clean_start = time.time()
            cleaned_content = M3U8Cleaner.clean_m3u8_content(m3u8_content)
            clean_time = time.time() - clean_start
            if clean_time > 0.1:
                logger.debug(f"z参数解析器: m3u8内容清理耗时: {clean_time:.2f}秒")

            # 处理m3u8中的#EXT-X-KEY：下载key并把URI改写为本服务地址
            try:
                key_start = time.time()
                cleaned_content, rewritten = rewrite_m3u8_key_uris(
                    m3u8_content=cleaned_content,
                    m3u8_url_for_base=final_m3u8_url_for_base,
                    api_base_url=self.api_base_url,
                    session=self.session,
                )
                key_time = time.time() - key_start
                if rewritten > 0:
                    logger.info(f"z参数解析器: KEY处理完成（改写{rewritten}处，耗时: {key_time:.2f}秒）")
            except Exception as e:
                logger.warning(f"z参数解析器: KEY处理失败（忽略，继续返回原m3u8）: {e}")
            
            # 生成文件名
            from datetime import datetime
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
            
            logger.info(f"z参数解析器: m3u8文件已下载并清理: {output_path}")
            
            # 存储文件映射
            self.m3u8_files[file_id] = str(output_path)
            
            # 返回API接口URL
            return f"{self.api_base_url}/api/v1/m3u8/{file_id}"
            
        except Exception as e:
            logger.warning(f"z参数解析器: 下载m3u8文件失败: {e}，返回原始URL")
            return None
    
    def get_m3u8_file_path(self, file_id: str) -> Optional[str]:
        """
        根据文件ID获取m3u8文件路径（支持从内存映射和文件系统查找）
        
        Args:
            file_id: 文件ID（16位hash）
        
        Returns:
            m3u8文件路径，如果不存在返回None
        """
        # 首先从内存映射中查找
        if file_id in self.m3u8_files:
            file_path = self.m3u8_files[file_id]
            if os.path.exists(file_path):
                return file_path
            else:
                # 文件不存在，从映射中移除
                del self.m3u8_files[file_id]
        
        # 从文件系统查找（基于文件ID的前缀匹配）
        cache_dir = project_root / "data" / "m3u8_cache"
        if cache_dir.exists():
            # 文件名格式：m3u8_{hash}_{timestamp}.m3u8
            # 查找hash部分以file_id开头的文件（file_id是hash的前16位）
            for file_path in cache_dir.glob("m3u8_*.m3u8"):
                file_name = file_path.stem  # 不含扩展名
                # 提取hash部分（m3u8_后面的部分，直到第一个下划线）
                parts = file_name.split('_')
                if len(parts) >= 2:
                    hash_part = parts[1]  # hash部分
                    # 检查hash的前16位是否匹配file_id
                    if hash_part.startswith(file_id):
                        if file_path.exists():
                            # 更新映射
                            self.m3u8_files[file_id] = str(file_path)
                            logger.debug(f"从文件系统找到m3u8文件: {file_id} -> {file_path}")
                            return str(file_path)
        
        logger.warning(f"未找到m3u8文件: file_id={file_id}")
        return None

