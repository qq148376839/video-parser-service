"""
数据库工具类
提供SQLite数据库连接管理、表结构初始化和基础CRUD操作
"""
import sqlite3
import json
import os
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
from datetime import datetime

from utils.logger import logger


class Database:
    """数据库工具类"""
    
    def __init__(self, db_path: str = None):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径（如果为None，使用默认路径）
        """
        # 确定数据库路径
        if db_path is None:
            # 优先使用 /app/data（Docker环境），否则使用 ./data（本地环境）
            if Path("/app/data").exists():
                data_dir = Path("/app/data")
            else:
                data_dir = Path("./data")
            
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "video_parser.db")
        
        self.db_path = db_path
        logger.info(f"数据库路径: {self.db_path}")
        
        # 初始化表结构
        self.init_tables()
    
    @contextmanager
    def get_connection(self):
        """
        获取数据库连接（上下文管理器）
        
        Yields:
            sqlite3.Connection: 数据库连接对象
        """
        # 增加超时时间，并启用WAL模式提高并发性能
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0  # 增加超时时间到30秒
        )
        conn.row_factory = sqlite3.Row  # 返回字典格式
        
        # 启用WAL模式（Write-Ahead Logging）提高并发性能
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception as e:
            logger.debug(f"启用WAL模式失败（可能不支持）: {e}")
        
        # 设置其他优化参数
        try:
            conn.execute("PRAGMA synchronous=NORMAL")  # 平衡性能和安全性
            conn.execute("PRAGMA busy_timeout=30000")  # 30秒忙等待
        except Exception as e:
            logger.debug(f"设置数据库参数失败: {e}")
        
        try:
            yield conn
            conn.commit()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                logger.warning(f"数据库锁定，等待后重试: {e}")
                # 等待一小段时间后重试
                import time
                time.sleep(0.1)
                conn.rollback()
                # 重新尝试提交
                try:
                    conn.commit()
                except Exception as retry_e:
                    logger.error(f"重试提交失败: {retry_e}")
                    raise
            else:
                conn.rollback()
                logger.error(f"数据库操作失败: {e}", exc_info=True)
                raise
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}", exc_info=True)
            raise
        finally:
            conn.close()
    
    def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            return column_name in columns
        except Exception:
            # 表不存在时返回False
            return False
    
    def _add_column_if_not_exists(self, cursor, table_name: str, column_name: str, column_def: str):
        """如果列不存在则添加列"""
        if not self._column_exists(cursor, table_name, column_name):
            try:
                # SQLite不支持在ALTER TABLE ADD COLUMN时使用CURRENT_TIMESTAMP等非常量默认值
                # 需要先添加列（不带默认值），然后如果需要，可以通过UPDATE设置值
                if "CURRENT_TIMESTAMP" in column_def.upper():
                    # 提取数据类型部分（去掉DEFAULT CURRENT_TIMESTAMP）
                    type_part = column_def.split("DEFAULT")[0].strip()
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {type_part}")
                    # 为新添加的列设置当前时间戳
                    cursor.execute(f"UPDATE {table_name} SET {column_name} = datetime('now') WHERE {column_name} IS NULL")
                    logger.info(f"已添加列 {table_name}.{column_name} (已设置默认值)")
                else:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
                    logger.info(f"已添加列 {table_name}.{column_name}")
            except Exception as e:
                logger.warning(f"添加列 {table_name}.{column_name} 失败: {e}")
    
    def init_tables(self):
        """初始化所有表结构"""
        logger.info("初始化数据库表结构...")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 搜索缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    keyword VARCHAR(255) PRIMARY KEY,
                    results JSON NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expire_at DATETIME,
                    hit_count INTEGER DEFAULT 0
                )
            """)
            
            # 检查并添加缺失的列（用于旧数据库迁移）
            self._add_column_if_not_exists(cursor, "search_cache", "expire_at", "DATETIME")
            self._add_column_if_not_exists(cursor, "search_cache", "hit_count", "INTEGER DEFAULT 0")
            
            # 创建索引（使用try-except处理可能失败的情况）
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_search_cache_keyword 
                    ON search_cache(keyword)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_search_cache_keyword 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_search_cache_updated_at 
                    ON search_cache(updated_at)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_search_cache_updated_at 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_search_cache_expire_at 
                    ON search_cache(expire_at)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_search_cache_expire_at 失败（可能已存在）: {e}")
            
            # 2. 注册信息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS registrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    uid VARCHAR(50),
                    "key" VARCHAR(255),
                    register_time DATETIME,
                    expire_date DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            # 检查并添加缺失的列（用于旧数据库迁移）
            self._add_column_if_not_exists(cursor, "registrations", "created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
            self._add_column_if_not_exists(cursor, "registrations", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
            self._add_column_if_not_exists(cursor, "registrations", "is_active", "INTEGER DEFAULT 1")
            
            # 创建索引
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_registrations_email 
                    ON registrations(email)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_registrations_email 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_registrations_id 
                    ON registrations(id)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_registrations_id 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_registrations_active 
                    ON registrations(is_active)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_registrations_active 失败（可能已存在）: {e}")
            
            # 3. 注册配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS registration_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_key VARCHAR(50) UNIQUE NOT NULL,
                    config_value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 插入默认配置
            cursor.execute("""
                INSERT OR IGNORE INTO registration_config (config_key, config_value) 
                VALUES ('current_index', '0')
            """)
            
            # 4. z参数缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS z_params_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    param_key VARCHAR(50) UNIQUE NOT NULL,
                    param_value TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expire_at DATETIME
                )
            """)
            
            # 检查并添加缺失的列
            self._add_column_if_not_exists(cursor, "z_params_cache", "expire_at", "DATETIME")
            
            # 创建索引
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_z_params_key 
                    ON z_params_cache(param_key)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_z_params_key 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_z_params_expire 
                    ON z_params_cache(expire_at)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_z_params_expire 失败（可能已存在）: {e}")
            
            # 5. URL解析缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS url_parse_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_url VARCHAR(500) UNIQUE NOT NULL,
                    m3u8_url TEXT NOT NULL,
                    m3u8_file_path TEXT,
                    file_id VARCHAR(50),
                    parse_method VARCHAR(50),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expire_at DATETIME,
                    hit_count INTEGER DEFAULT 0
                )
            """)
            
            # 检查并添加缺失的列（用于旧数据库迁移）
            self._add_column_if_not_exists(cursor, "url_parse_cache", "expire_at", "DATETIME")
            self._add_column_if_not_exists(cursor, "url_parse_cache", "hit_count", "INTEGER DEFAULT 0")
            
            # 创建索引
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_url_parse_cache_url 
                    ON url_parse_cache(video_url)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_url_parse_cache_url 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_url_parse_cache_updated_at 
                    ON url_parse_cache(updated_at)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_url_parse_cache_updated_at 失败（可能已存在）: {e}")
            
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS ix_url_parse_cache_expire_at 
                    ON url_parse_cache(expire_at)
                """)
            except Exception as e:
                logger.debug(f"创建索引 ix_url_parse_cache_expire_at 失败（可能已存在）: {e}")
            
            conn.commit()
            logger.info("数据库表结构初始化完成")
    
    def execute_query(self, query: str, params: tuple = (), max_retries: int = 3) -> List[Dict]:
        """
        执行查询操作（带重试机制）
        
        Args:
            query: SQL查询语句
            params: 查询参数
            max_retries: 最大重试次数
        
        Returns:
            查询结果列表（字典格式）
        """
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    import time
                    wait_time = 0.1 * (attempt + 1)  # 指数退避
                    logger.debug(f"数据库锁定，等待 {wait_time} 秒后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                raise
    
    def execute_update(self, query: str, params: tuple = (), max_retries: int = 3) -> int:
        """
        执行更新操作（INSERT/UPDATE/DELETE）（带重试机制）
        
        Args:
            query: SQL更新语句
            params: 更新参数
            max_retries: 最大重试次数
        
        Returns:
            受影响的行数
        """
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    return cursor.rowcount
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    import time
                    wait_time = 0.1 * (attempt + 1)  # 指数退避
                    logger.debug(f"数据库锁定，等待 {wait_time} 秒后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                raise
    
    def execute_one(self, query: str, params: tuple = ()) -> Optional[Dict]:
        """
        执行查询并返回单条记录
        
        Args:
            query: SQL查询语句
            params: 查询参数
        
        Returns:
            单条记录（字典格式），如果不存在返回None
        """
        results = self.execute_query(query, params)
        return results[0] if results else None
    
    def close(self):
        """关闭数据库连接（SQLite会自动管理，此方法保留用于兼容性）"""
        pass


# 全局数据库实例（延迟初始化）
_db_instance: Optional[Database] = None


def get_database(db_path: str = None) -> Database:
    """
    获取全局数据库实例（单例模式）
    
    Args:
        db_path: 数据库文件路径（仅在首次调用时有效）
    
    Returns:
        Database实例
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance
