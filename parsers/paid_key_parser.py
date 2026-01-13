"""
2s0解析器模块
使用付费key获取m3u8 URL（第一优先级方案）
基于get_m3u8_with_paid_key.py的PaidKeyM3U8Getter类
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
from requests.exceptions import Timeout, RequestException, SSLError
import re
import json
import os
from urllib.parse import quote, urljoin
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from pathlib import Path
from utils.logger import logger
from utils.file_lock import FileLock
from utils.m3u8_cleaner import M3U8Cleaner
from utils.m3u8_key_rewriter import rewrite_m3u8_key_uris
from utils.database import get_database


class PaidKeyM3U8Getter:
    """使用付费key获取m3u8 URL（支持多key轮询）"""
    
    def __init__(self, json_file: str = None):
        """
        初始化
        
        参数:
            json_file: 包含key信息的JSON文件路径（如果为None，使用默认路径）
        """
        # 如果没有指定json_file，使用默认路径 data/registration_results.json
        if json_file is None:
            json_file = str(project_root / "data" / "registration_results.json")
        
        # 如果是相对路径，尝试从项目根目录查找
        if not os.path.isabs(json_file):
            root_path = str(project_root / json_file)
            
            # 优先使用项目根目录的文件
            if os.path.exists(root_path):
                self.json_file = root_path
            elif os.path.exists(json_file):
                self.json_file = os.path.abspath(json_file)
            else:
                self.json_file = json_file
        else:
            self.json_file = json_file
        
        self.session = requests.Session()
        # 优化连接池设置，提高性能
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=0  # 禁用自动重试，由业务逻辑控制
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        self.current_uid = None
        self.current_key = None
    
    def load_keys(self) -> Dict:
        """加载key信息（从数据库读取）"""
        import time
        load_start = time.time()
        
        try:
            db = get_database()
            
            # 从数据库加载keys
            query_start = time.time()
            keys_records = db.execute_query(
                """
                SELECT email, password, uid, "key", register_time, expire_date
                FROM registrations
                WHERE is_active = 1
                ORDER BY id
                """
            )
            query_time = time.time() - query_start
            if query_time > 0.5:
                logger.info(f"2s0解析器: 查询keys耗时: {query_time:.2f}秒 (共{len(keys_records)}条记录)")
            
            # 转换为列表格式
            convert_start = time.time()
            keys = []
            for record in keys_records:
                keys.append({
                    'email': record['email'],
                    'password': record['password'],
                    'uid': record['uid'],
                    'key': record['key'],
                    'register_time': record['register_time'],
                    'expire_date': record['expire_date']
                })
            convert_time = time.time() - convert_start
            if convert_time > 0.5:
                logger.info(f"2s0解析器: 转换keys格式耗时: {convert_time:.2f}秒")
            
            # 获取current_index
            config_start = time.time()
            config = db.execute_one(
                "SELECT config_value FROM registration_config WHERE config_key = 'current_index'"
            )
            config_time = time.time() - config_start
            if config_time > 0.5:
                logger.info(f"2s0解析器: 查询current_index耗时: {config_time:.2f}秒")
            
            current_index = int(config['config_value']) if config else 0
            
            # 构建返回数据（兼容旧格式）
            data = {
                'current_index': current_index,
                'keys': keys
            }
            
            total_time = time.time() - load_start
            if total_time > 0.5:
                logger.info(f"2s0解析器: load_keys()总耗时: {total_time:.2f}秒")
            
            return data
            
        except Exception as e:
            logger.error(f"2s0解析器: 从数据库加载key信息失败: {e}", exc_info=True)
            # 降级到JSON文件（如果存在）
            json_path = Path(self.json_file)
            if json_path.exists():
                logger.warning("降级到JSON文件读取")
                try:
                    with FileLock.lock_file(json_path, timeout=5.0) as f:
                        data = json.load(f)
                    return data
                except Exception as json_e:
                    logger.error(f"读取JSON文件也失败: {json_e}")
            raise FileNotFoundError(f"无法加载key信息: {e}")
    
    def save_keys(self, data: Dict) -> None:
        """保存key信息（保存到数据库）"""
        import time
        save_start = time.time()
        
        try:
            db = get_database()
            
            # 保存current_index
            current_index = data.get('current_index', 0)
            config_start = time.time()
            db.execute_update(
                """
                INSERT OR REPLACE INTO registration_config (config_key, config_value, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                ('current_index', str(current_index))
            )
            config_time = time.time() - config_start
            if config_time > 0.5:
                logger.info(f"2s0解析器: 保存current_index耗时: {config_time:.2f}秒")
            
            # 保存keys（更新现有记录）
            keys = data.get('keys', [])
            keys_save_start = time.time()
            for key_info in keys:
                email = key_info.get('email')
                if not email:
                    continue
                
                db.execute_update(
                    """
                    INSERT OR REPLACE INTO registrations 
                    (email, password, uid, "key", register_time, expire_date, updated_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 1)
                    """,
                    (
                        email,
                        key_info.get('password', ''),
                        key_info.get('uid'),
                        key_info.get('key'),
                        key_info.get('register_time'),
                        key_info.get('expire_date')
                    )
                )
            
            keys_save_time = time.time() - keys_save_start
            total_time = time.time() - save_start
            if keys_save_time > 0.5 or total_time > 0.5:
                logger.info(f"2s0解析器: 保存keys耗时: {keys_save_time:.2f}秒 (共{len(keys)}个key, 总耗时: {total_time:.2f}秒)")
            else:
                logger.debug(f"2s0解析器: 已保存 {len(keys)} 个key到数据库 (耗时: {total_time:.2f}秒)")
            
        except Exception as e:
            logger.error(f"2s0解析器: 保存key信息到数据库失败: {e}", exc_info=True)
            # 降级到JSON文件（如果文件路径存在）
            json_path = Path(self.json_file)
            if json_path.parent.exists():
                logger.warning("降级到JSON文件保存")
                try:
                    with FileLock.lock_file(json_path, timeout=5.0) as f:
                        f.seek(0)
                        f.truncate(0)
                        json.dump(data, f, indent=2, ensure_ascii=False)
                except Exception as json_e:
                    logger.error(f"保存JSON文件也失败: {json_e}")
    
    def update_json_structure(self, keys: List[Dict]) -> tuple:
        """更新JSON结构，添加expire_date字段"""
        updated = False
        for key_info in keys:
            # 添加expire_date字段（如果不存在）
            if 'expire_date' not in key_info:
                register_time = datetime.strptime(key_info['register_time'], '%Y-%m-%d %H:%M:%S')
                expire_date = register_time + timedelta(days=355)
                key_info['expire_date'] = expire_date.strftime('%Y-%m-%d %H:%M:%S')
                updated = True
        return keys, updated
    
    def is_key_expired(self, key_info: Dict) -> bool:
        """检查key是否过期"""
        if 'expire_date' not in key_info:
            return False
        
        expire_date = datetime.strptime(key_info['expire_date'], '%Y-%m-%d %H:%M:%S')
        return datetime.now() > expire_date
    
    def get_next_valid_key(self) -> Optional[Dict]:
        """
        获取下一个有效的key（通过SQL直接查询）
        
        轮询逻辑：
        - 基于current_index获取下一个有效的key
        - 如果当前索引的key无效（过期或is_active=0），继续查找下一个
        - 如果遍历完所有key都没找到有效的，重置索引并返回None
        """
        import time
        get_key_start = time.time()
        
        try:
            db = get_database()
            
            # 1. 获取当前索引
            config_start = time.time()
            config = db.execute_one(
                "SELECT config_value FROM registration_config WHERE config_key = 'current_index'"
            )
            current_index = int(config['config_value']) if config and config.get('config_value') else 0
            config_time = time.time() - config_start
            if config_time > 0.5:
                logger.info(f"2s0解析器: 查询current_index耗时: {config_time:.2f}秒")
            
            # 2. 获取所有有效keys的总数（用于轮询）
            count_start = time.time()
            count_result = db.execute_one(
                """
                SELECT COUNT(*) as total
                FROM registrations
                WHERE is_active = 1 AND (expire_date IS NULL OR expire_date > datetime('now'))
                """
            )
            total_valid_keys = count_result['total'] if count_result else 0
            count_time = time.time() - count_start
            if count_time > 0.5:
                logger.info(f"2s0解析器: 查询有效keys总数耗时: {count_time:.2f}秒")
            
            if total_valid_keys == 0:
                logger.warning("2s0解析器: 没有有效的key")
                return None
            
            # 3. 确保current_index在有效范围内
            if current_index >= total_valid_keys:
                current_index = 0
            
            # 4. 查询下一个有效的key（基于current_index轮询）
            # 思路：获取所有有效keys，按id排序，跳过current_index个，取1个
            query_start = time.time()
            key_record = db.execute_one(
                """
                SELECT email, password, uid, "key", register_time, expire_date
                FROM registrations
                WHERE is_active = 1 AND (expire_date IS NULL OR expire_date > datetime('now'))
                ORDER BY id
                LIMIT 1 OFFSET ?
                """,
                (current_index,)
            )
            query_time = time.time() - query_start
            if query_time > 0.5:
                logger.info(f"2s0解析器: 查询有效key耗时: {query_time:.2f}秒")
            
            if not key_record:
                # 如果当前索引没有找到，说明已经到末尾，重置索引并重新查询
                logger.debug("2s0解析器: 当前索引已到末尾，重置索引")
                current_index = 0
                key_record = db.execute_one(
                    """
                    SELECT email, password, uid, "key", register_time, expire_date
                    FROM registrations
                    WHERE is_active = 1 AND (expire_date IS NULL OR expire_date > datetime('now'))
                    ORDER BY id
                    LIMIT 1 OFFSET 0
                    """
                )
            
            if not key_record:
                logger.warning("2s0解析器: 未找到有效的key")
                return None
            
            # 5. 转换为字典格式
            key_info = {
                'email': key_record['email'],
                'password': key_record['password'],
                'uid': key_record['uid'],
                'key': key_record['key'],
                'register_time': key_record['register_time'],
                'expire_date': key_record['expire_date']
            }
            
            # 6. 更新current_index到下一个位置（循环）
            next_index = (current_index + 1) % total_valid_keys if total_valid_keys > 0 else 0
            
            update_start = time.time()
            db.execute_update(
                """
                INSERT OR REPLACE INTO registration_config (config_key, config_value, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                ('current_index', str(next_index))
            )
            update_time = time.time() - update_start
            if update_time > 0.5:
                logger.info(f"2s0解析器: 更新current_index耗时: {update_time:.2f}秒")
            
            total_time = time.time() - get_key_start
            if total_time > 0.5:
                logger.info(f"2s0解析器: get_next_valid_key()总耗时: {total_time:.2f}秒")
            
            return key_info
            
        except Exception as e:
            logger.error(f"2s0解析器: 获取有效key失败: {e}", exc_info=True)
            return None
    
    def get_m3u8_url(self, video_url: str, retry: bool = True) -> Optional[str]:
        """
        获取m3u8 URL（自动轮询key）
        
        参数:
            video_url: 视频URL（如：https://www.iqiyi.com/v_1c168e2yzbk.html）
            retry: 如果失败是否重试下一个key
        
        返回:
            m3u8 URL或None
        """
        import time
        get_url_start = time.time()
        
        # 获取下一个有效的key
        get_key_start = time.time()
        key_info = self.get_next_valid_key()
        get_key_time = time.time() - get_key_start
        if get_key_time > 0.1:  # 降低阈值，记录所有获取key的耗时
            logger.info(f"2s0解析器: 获取下一个有效key耗时: {get_key_time:.3f}秒")
        
        if not key_info:
            logger.warning("2s0解析器: 没有可用的key")
            return None
        
        uid = key_info['uid']
        key = key_info['key']
        self.current_uid = uid
        self.current_key = key

        # 新版2s0接口：返回m3u8文件内容（或直接返回m3u8直链）
        # 示例：
        # https://json.2s0.cn:5678/home/api?type=app&uid=...&key=...&url=...
        url = f"https://json.2s0.cn:5678/home/api?type=app&uid={uid}&key={key}&url={quote(video_url)}"
        
        try:
            # 记录请求开始时间
            api_request_start = time.time()
            logger.debug(f"2s0解析器: 开始API请求: {url[:100]}... (uid={uid})")
            
            # 优化超时设置：连接超时5秒，读取超时10秒（总共最多15秒）
            # 如果API正常只需要900ms，15秒应该足够，避免等待太久
            try:
                # 注意：home/api在部分key下会302跳转到cachem3u8.2s0.cn（证书可能过期）
                # 这里禁用自动跳转，避免requests在跟随跳转时触发SSL验证失败而直接报错。
                response = self.session.get(url, timeout=(5, 10), allow_redirects=False)
            except Timeout as e:
                api_request_time = time.time() - api_request_start
                logger.error(f"2s0解析器: API请求超时: {api_request_time:.2f}秒 (uid={uid}, 超时设置: 连接5秒/读取10秒)")
                raise
            except SSLError as e:
                api_request_time = time.time() - api_request_start
                logger.error(f"2s0解析器: API请求SSL错误: {e} (耗时: {api_request_time:.2f}秒, uid={uid})")
                raise
            except RequestException as e:
                api_request_time = time.time() - api_request_start
                logger.error(f"2s0解析器: API请求异常: {e} (耗时: {api_request_time:.2f}秒, uid={uid})")
                raise
            
            api_request_time = time.time() - api_request_start
            if api_request_time > 2.0:  # 如果超过2秒，记录警告
                logger.warning(f"2s0解析器: API请求耗时较长: {api_request_time:.2f}秒 (uid={uid}, 正常应该<1秒)")
            else:
                logger.info(f"2s0解析器: API请求耗时: {api_request_time:.2f}秒 (uid={uid})")
            # 302/301等跳转：直接返回Location（通常是m3u8直链）
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location") or response.headers.get("location")
                if location:
                    logger.info(f"2s0解析器: home/api返回跳转({response.status_code})，使用Location作为m3u8直链")
                    return location
                logger.warning(f"2s0解析器: home/api返回跳转({response.status_code})但无Location (uid={uid})")
                if retry:
                    logger.info(f"2s0解析器: 尝试下一个key... (当前key耗时: {time.time() - get_url_start:.2f}秒)")
                    return self.get_m3u8_url(video_url, retry=False)
                return None

            if response.status_code == 200:
                body = response.text or ""

                # 1) 直接返回m3u8文件内容（推荐路径）
                if "#EXTM3U" in body:
                    total_time = time.time() - get_url_start
                    logger.info(f"2s0解析器: 使用key成功(返回m3u8内容): uid={uid}, email={key_info.get('email', 'N/A')} (总耗时: {total_time:.2f}秒)")
                    # 让后续download_m3u8_file直接下载该URL并写入缓存文件
                    return url

                # 2) 兼容旧响应：HTML/JSON里包含m3u8直链
                extract_start = time.time()
                m3u8_match = re.search(r'var url = "([^"]+)"', body)
                if not m3u8_match:
                    m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', body)
                extract_time = time.time() - extract_start
                if extract_time > 0.1:
                    logger.debug(f"2s0解析器: 提取m3u8信息耗时: {extract_time:.2f}秒")

                if m3u8_match:
                    m3u8_url = m3u8_match.group(1)
                    total_time = time.time() - get_url_start
                    logger.info(f"2s0解析器: 使用key成功(返回m3u8直链): uid={uid}, email={key_info.get('email', 'N/A')} (总耗时: {total_time:.2f}秒)")
                    return m3u8_url

                logger.warning(f"2s0解析器: 未识别到m3u8内容或直链 (uid={uid})")
                if retry:
                    logger.info(f"2s0解析器: 尝试下一个key... (当前key耗时: {time.time() - get_url_start:.2f}秒)")
                    return self.get_m3u8_url(video_url, retry=False)
                return None
            else:
                logger.warning(f"2s0解析器: 请求失败: {response.status_code} (uid={uid})")
                # 如果允许重试，尝试下一个key
                if retry:
                    logger.info(f"2s0解析器: 尝试下一个key... (当前key耗时: {time.time() - get_url_start:.2f}秒)")
                    return self.get_m3u8_url(video_url, retry=False)
                return None
        except Exception as e:
            total_time = time.time() - get_url_start
            logger.warning(f"2s0解析器: 错误: {e} (uid={uid}, 耗时: {total_time:.2f}秒)")
            # 如果允许重试，尝试下一个key
            if retry:
                logger.info(f"2s0解析器: 尝试下一个key... (当前key耗时: {total_time:.2f}秒)")
                return self.get_m3u8_url(video_url, retry=False)
            return None
    
    def download_m3u8_file(self, m3u8_url: str, output_path: str = None) -> Optional[str]:
        """
        下载m3u8文件本身（文本文件）
        
        如果相同hash的文件已存在，直接返回现有文件，避免重复下载
        
        参数:
            m3u8_url: m3u8 URL
            output_path: 输出文件路径（如果不指定，自动生成到data/m3u8_cache目录）
        
        返回:
            下载的m3u8文件路径或None
        """
        if not m3u8_url:
            logger.error("2s0解析器: m3u8 URL为空")
            return None
        
        # 创建缓存目录
        cache_dir = project_root / "data" / "m3u8_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 从URL提取hash
        hash_match = re.search(r'/Cache/[^/]+/([a-f0-9]+)\.m3u8', m3u8_url)
        
        # 如果指定了输出路径，直接使用
        if output_path:
            if os.path.exists(output_path):
                logger.debug(f"2s0解析器: m3u8文件已存在，使用缓存: {output_path}")
                return output_path
        else:
            # 检查是否已有相同hash的文件存在
            if hash_match:
                hash_value = hash_match.group(1)
                # 查找所有以该hash开头的文件
                existing_files = list(cache_dir.glob(f"m3u8_{hash_value}_*.m3u8"))
                if existing_files:
                    # 使用最新的文件（按修改时间）
                    latest_file = max(existing_files, key=lambda p: p.stat().st_mtime)
                    logger.info(f"2s0解析器: 发现已存在的m3u8文件（hash={hash_value}），使用缓存: {latest_file}")
                    return str(latest_file)
        
        logger.debug(f"2s0解析器: 开始下载m3u8文件: {m3u8_url[:100]}...")
        
        try:
            import time
            download_start = time.time()
            # 下载m3u8文件内容
            try:
                response = self.session.get(m3u8_url, timeout=30)
                response.raise_for_status()
            except SSLError as e:
                # 兼容：cachem3u8.2s0.cn 证书过期时，降级跳过证书校验重试一次
                logger.warning(f"2s0解析器: 下载m3u8遇到SSL错误，降级verify=False重试: {e}")
                response = self.session.get(m3u8_url, timeout=30, verify=False)
                response.raise_for_status()
            m3u8_content = response.text
            download_time = time.time() - download_start
            logger.debug(f"2s0解析器: 下载m3u8内容耗时: {download_time:.2f}秒")
            
            # 生成输出文件名
            if not output_path:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                if hash_match:
                    # 使用hash + 时间戳
                    base_name = f"m3u8_{hash_match.group(1)}_{timestamp}"
                else:
                    # 如果没有hash，使用URL的MD5 + 时间戳
                    import hashlib
                    url_hash = hashlib.md5(m3u8_url.encode('utf-8')).hexdigest()[:16]
                    base_name = f"m3u8_{url_hash}_{timestamp}"
                
                output_path = str(cache_dir / f"{base_name}.m3u8")
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 将m3u8内容中的相对路径转换为绝对URL
            convert_start = time.time()
            m3u8_content = self._convert_relative_paths_to_absolute(m3u8_content, m3u8_url)
            convert_time = time.time() - convert_start
            if convert_time > 0.1:
                logger.debug(f"2s0解析器: 相对路径转换耗时: {convert_time:.2f}秒")

            # 处理m3u8中的#EXT-X-KEY：下载key并把URI改写为本服务地址，避免原始key地址过期/崩溃
            try:
                key_start = time.time()
                api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
                m3u8_content, rewritten = rewrite_m3u8_key_uris(
                    m3u8_content=m3u8_content,
                    m3u8_url_for_base=m3u8_url,
                    api_base_url=api_base_url,
                    session=self.session,
                )
                key_time = time.time() - key_start
                if rewritten > 0:
                    logger.info(f"2s0解析器: KEY处理完成（改写{rewritten}处，耗时: {key_time:.2f}秒）")
            except Exception as e:
                logger.warning(f"2s0解析器: KEY处理失败（忽略，继续返回原m3u8）: {e}")
            
            # 清理m3u8内容
            clean_start = time.time()
            cleaned_content = M3U8Cleaner.clean_m3u8_content(m3u8_content)
            clean_time = time.time() - clean_start
            if clean_time > 0.1:
                logger.debug(f"2s0解析器: 清理m3u8内容耗时: {clean_time:.2f}秒")
            
            # 保存m3u8文件
            save_start = time.time()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)
            save_time = time.time() - save_start
            if save_time > 0.1:
                logger.debug(f"2s0解析器: 保存m3u8文件耗时: {save_time:.2f}秒")
            
            file_size = os.path.getsize(output_path)
            logger.info(f"2s0解析器: m3u8文件下载成功: {output_path} (大小: {file_size} 字节, 片段数: {cleaned_content.count('#EXTINF')})")
            
            return output_path
            
        except Exception as e:
            logger.error(f"2s0解析器: 下载m3u8文件失败: {e}")
            return None
    
    def _convert_relative_paths_to_absolute(self, m3u8_content: str, base_url: str) -> str:
        """
        将m3u8内容中的相对路径转换为绝对URL
        
        Args:
            m3u8_content: m3u8文件内容
            base_url: 用于转换相对路径的基础URL
        
        Returns:
            转换后的m3u8内容
        """
        lines = m3u8_content.split('\n')
        converted_lines = []
        converted_count = 0
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # 处理#EXT-X-KEY标签中的URI属性
            # 格式: #EXT-X-KEY:METHOD=AES-128,URI="enc.key",IV=...
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
            logger.info(f"2s0解析器: 已将 {converted_count} 个相对路径转换为绝对URL")
        
        return '\n'.join(converted_lines) if converted_lines else m3u8_content


class PaidKeyParser:
    """2s0解析器（第一优先级方案）"""
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        初始化2s0解析器
        
        Args:
            api_base_url: API服务的基础URL，用于生成m3u8文件的访问链接
        """
        # 使用默认路径 data/registration_results.json
        json_file = str(project_root / "data" / "registration_results.json")
        self.getter = PaidKeyM3U8Getter(json_file)
        self.api_base_url = api_base_url.rstrip('/')
        # 存储m3u8文件路径的映射 {file_id: file_path}
        self.m3u8_files = {}
        # 存储取消事件 {video_url: threading.Event}
        self._cancellation_events = {}
        logger.info("2s0解析器初始化完成")
    
    def set_cancellation_event(self, video_url: str, event):
        """
        设置取消事件，用于中断解析
        
        Args:
            video_url: 视频URL
            event: threading.Event对象
        """
        self._cancellation_events[video_url] = event
    
    def _is_cancelled(self, video_url: str) -> bool:
        """
        检查是否已取消
        
        Args:
            video_url: 视频URL
        
        Returns:
            是否已取消
        """
        if video_url in self._cancellation_events:
            return self._cancellation_events[video_url].is_set()
        return False
    
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
    
    def parse(self, video_url: str, max_retries: int = 2) -> Optional[str]:
        """
        解析视频URL，返回m3u8链接（本地API接口）
        
        支持失败重试机制：最多重试2次，如果都失败则返回None，让调用者切换到下一个解析器
        
        Args:
            video_url: 视频URL（如果包含$分隔的多集URL，只解析第一个）
            max_retries: 最大重试次数（默认2次）
        
        Returns:
            本地API接口的m3u8链接，如果失败返回None
        """
        import time
        start_time = time.time()
        
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
                logger.debug(f"2s0解析器: 检测到多集URL，只解析第一集: {video_url[:100]}...")
        
        # 验证URL格式
        if not video_url or not video_url.startswith(('http://', 'https://')):
            logger.error(f"2s0解析器: 无效的视频URL格式: {video_url}")
            return None
        
        # 重试机制：最多重试max_retries次
        for attempt in range(max_retries + 1):  # 0, 1, 2 共3次（首次+2次重试）
            attempt_start = time.time()
            # 检查是否已取消
            if self._is_cancelled(video_url):
                logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                return None
            
            try:
                if attempt > 0:
                    logger.info(f"2s0解析器: 第{attempt}次重试解析: {video_url[:100]}...")
                else:
                    logger.info(f"2s0解析器: 使用2s0方案解析: {video_url[:100]}...")
                
                # 调用getter获取m3u8 URL（内部已有key轮询重试机制）
                get_url_start = time.time()
                m3u8_url = self.getter.get_m3u8_url(video_url, retry=True)
                get_url_time = time.time() - get_url_start
                logger.info(f"2s0解析器: 获取m3u8 URL耗时: {get_url_time:.2f}秒")
                
                # 再次检查是否已取消（在获取URL后）
                if self._is_cancelled(video_url):
                    logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                    return None
                
                if not m3u8_url:
                    # 检查是否已取消
                    if self._is_cancelled(video_url):
                        logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                        return None
                    if attempt < max_retries:
                        logger.warning(f"2s0解析器: 第{attempt+1}次尝试失败，准备重试...")
                        continue
                    else:
                        logger.warning(f"2s0解析器: 解析失败（已重试{max_retries}次），无法获取m3u8 URL")
                        return None
                
                logger.info(f"2s0解析器: 获取到m3u8 URL: {m3u8_url[:100]}...")
                
                # 检查是否已取消（在下载前）
                if self._is_cancelled(video_url):
                    logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                    return None
                
                # 下载m3u8文件
                download_start = time.time()
                m3u8_file_path = self.getter.download_m3u8_file(m3u8_url)
                download_time = time.time() - download_start
                logger.info(f"2s0解析器: 下载m3u8文件耗时: {download_time:.2f}秒")
                
                if not m3u8_file_path:
                    # 检查是否已取消
                    if self._is_cancelled(video_url):
                        logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                        return None
                    if attempt < max_retries:
                        logger.warning(f"2s0解析器: 第{attempt+1}次尝试下载m3u8文件失败，准备重试...")
                        continue
                    else:
                        logger.error(f"2s0解析器: 下载m3u8文件失败（已重试{max_retries}次）")
                        return None
                
                # 生成文件ID并存储映射
                file_id = self._generate_file_id(m3u8_url)
                self.m3u8_files[file_id] = m3u8_file_path
                
                # 生成本地API接口URL
                local_api_url = f"{self.api_base_url}/api/v1/m3u8/{file_id}"
                attempt_time = time.time() - attempt_start
                total_time = time.time() - start_time
                if attempt > 0:
                    logger.info(f"2s0解析器: 重试成功，返回本地API接口: {local_api_url} (本次尝试耗时: {attempt_time:.2f}秒, 总耗时: {total_time:.2f}秒)")
                else:
                    logger.info(f"2s0解析器: 解析成功，返回本地API接口: {local_api_url} (总耗时: {total_time:.2f}秒)")
                
                return local_api_url
                    
            except Exception as e:
                attempt_time = time.time() - attempt_start
                # 检查是否已取消
                if self._is_cancelled(video_url):
                    logger.info(f"2s0解析器: 检测到取消信号，中断解析: {video_url[:100]}...")
                    return None
                if attempt < max_retries:
                    logger.warning(f"2s0解析器: 第{attempt+1}次尝试异常: {e}，准备重试... (本次尝试耗时: {attempt_time:.2f}秒)")
                    continue
                else:
                    total_time = time.time() - start_time
                    logger.error(f"2s0解析器: 解析异常（已重试{max_retries}次）: {e} (总耗时: {total_time:.2f}秒)")
                    return None
        
        # 所有重试都失败
        logger.warning(f"2s0解析器: 解析失败（已重试{max_retries}次），将切换到下一个解析器")
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
