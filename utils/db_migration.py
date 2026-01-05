"""
数据迁移工具
负责将JSON文件数据迁移到数据库
"""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from utils.logger import logger
from utils.database import get_database
from utils.file_lock import FileLock


class DBMigration:
    """数据迁移工具类"""
    
    def __init__(self, db_path: str = None):
        """
        初始化迁移工具
        
        Args:
            db_path: 数据库文件路径
        """
        self.db = get_database(db_path)
        
        # 确定数据目录
        if Path("/app/data").exists():
            self.data_dir = Path("/app/data")
        else:
            self.data_dir = Path("./data")
        
        self.registration_file = self.data_dir / "registration_results.json"
        self.z_params_file = self.data_dir / "z_params.json"
    
    def backup_json_files(self) -> bool:
        """
        备份JSON文件
        
        Returns:
            是否备份成功
        """
        try:
            backup_dir = self.data_dir / "backups"
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 备份registration_results.json
            if self.registration_file.exists():
                backup_file = backup_dir / f"registration_results_{timestamp}.json.bak"
                shutil.copy2(self.registration_file, backup_file)
                logger.info(f"已备份 registration_results.json 到: {backup_file}")
            
            # 备份z_params.json
            if self.z_params_file.exists():
                backup_file = backup_dir / f"z_params_{timestamp}.json.bak"
                shutil.copy2(self.z_params_file, backup_file)
                logger.info(f"已备份 z_params.json 到: {backup_file}")
            
            return True
        except Exception as e:
            logger.error(f"备份JSON文件失败: {e}", exc_info=True)
            return False
    
    def migrate_registration_results(self) -> bool:
        """
        迁移 registration_results.json 到数据库
        
        Returns:
            是否迁移成功
        """
        if not self.registration_file.exists():
            logger.info("registration_results.json 不存在，跳过迁移")
            return True
        
        try:
            logger.info("开始迁移 registration_results.json...")
            
            # 读取JSON文件（使用文件锁）
            try:
                with FileLock.lock_file(self.registration_file, timeout=5.0) as f:
                    data = json.load(f)
            except TimeoutError:
                logger.warning("获取文件锁超时，尝试直接读取")
                with open(self.registration_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # 提取current_index
            current_index = data.get('current_index', 0)
            
            # 更新配置表
            self.db.execute_update(
                """
                INSERT OR REPLACE INTO registration_config (config_key, config_value, updated_at)
                VALUES (?, ?, ?)
                """,
                ('current_index', str(current_index), datetime.now().isoformat())
            )
            logger.info(f"已更新 current_index: {current_index}")
            
            # 迁移keys数组
            keys = data.get('keys', [])
            migrated_count = 0
            updated_count = 0
            
            for key_info in keys:
                email = key_info.get('email')
                if not email:
                    logger.warning("跳过无效的key信息（缺少email）")
                    continue
                
                # 检查是否已存在
                existing = self.db.execute_one(
                    "SELECT id FROM registrations WHERE email = ?",
                    (email,)
                )
                
                if existing:
                    # 更新现有记录
                    self.db.execute_update(
                        """
                        UPDATE registrations 
                        SET password = ?, uid = ?, "key" = ?, 
                            register_time = ?, expire_date = ?,
                            updated_at = ?, is_active = ?
                        WHERE email = ?
                        """,
                        (
                            key_info.get('password', ''),
                            key_info.get('uid'),
                            key_info.get('key'),
                            key_info.get('register_time'),
                            key_info.get('expire_date'),
                            datetime.now().isoformat(),
                            1,  # is_active
                            email
                        )
                    )
                    updated_count += 1
                else:
                    # 插入新记录
                    self.db.execute_update(
                        """
                        INSERT INTO registrations 
                        (email, password, uid, "key", register_time, expire_date, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            email,
                            key_info.get('password', ''),
                            key_info.get('uid'),
                            key_info.get('key'),
                            key_info.get('register_time'),
                            key_info.get('expire_date'),
                            1  # is_active
                        )
                    )
                    migrated_count += 1
            
            logger.info(f"registration_results.json 迁移完成: 新增 {migrated_count} 条，更新 {updated_count} 条")
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"解析 registration_results.json 失败: {e}")
            return False
        except Exception as e:
            logger.error(f"迁移 registration_results.json 失败: {e}", exc_info=True)
            return False
    
    def migrate_z_params(self) -> bool:
        """
        迁移 z_params.json 到数据库
        
        Returns:
            是否迁移成功
        """
        if not self.z_params_file.exists():
            logger.info("z_params.json 不存在，跳过迁移")
            return True
        
        try:
            logger.info("开始迁移 z_params.json...")
            
            # 读取JSON文件（使用文件锁）
            try:
                with FileLock.lock_file(self.z_params_file, timeout=5.0) as f:
                    data = json.load(f)
            except TimeoutError:
                logger.warning("获取文件锁超时，尝试直接读取")
                with open(self.z_params_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # 迁移各个参数
            params_mapping = {
                'z_param': 'z_param',
                's1ig_param': 's1ig_param',
                'g_param': 'g_param'
            }
            
            migrated_count = 0
            
            for json_key, db_key in params_mapping.items():
                value = data.get(json_key)
                if value is None:
                    continue
                
                # 检查是否已存在
                existing = self.db.execute_one(
                    "SELECT id FROM z_params_cache WHERE param_key = ?",
                    (db_key,)
                )
                
                # 计算过期时间（如果存在expires_in）
                expire_at = None
                if 'expires_in' in data and 'updated_at' in data:
                    try:
                        updated_at = datetime.fromisoformat(data['updated_at'])
                        expires_in = data.get('expires_in', 86400)  # 默认24小时
                        expire_at = (updated_at + timedelta(seconds=expires_in)).isoformat()
                    except Exception as e:
                        logger.warning(f"计算过期时间失败: {e}")
                
                if existing:
                    # 更新现有记录
                    self.db.execute_update(
                        """
                        UPDATE z_params_cache 
                        SET param_value = ?, updated_at = ?, expire_at = ?
                        WHERE param_key = ?
                        """,
                        (
                            str(value),
                            data.get('updated_at', datetime.now().isoformat()),
                            expire_at,
                            db_key
                        )
                    )
                else:
                    # 插入新记录
                    self.db.execute_update(
                        """
                        INSERT INTO z_params_cache 
                        (param_key, param_value, updated_at, expire_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            db_key,
                            str(value),
                            data.get('updated_at', datetime.now().isoformat()),
                            expire_at
                        )
                    )
                    migrated_count += 1
            
            logger.info(f"z_params.json 迁移完成: 处理 {migrated_count} 个参数")
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"解析 z_params.json 失败: {e}")
            return False
        except Exception as e:
            logger.error(f"迁移 z_params.json 失败: {e}", exc_info=True)
            return False
    
    def migrate_all(self) -> bool:
        """
        迁移所有JSON文件到数据库
        
        Returns:
            是否全部迁移成功
        """
        logger.info("=" * 60)
        logger.info("开始数据迁移")
        logger.info("=" * 60)
        
        # 备份原文件
        if not self.backup_json_files():
            logger.warning("备份失败，但继续迁移")
        
        # 迁移registration_results.json
        success1 = self.migrate_registration_results()
        
        # 迁移z_params.json
        success2 = self.migrate_z_params()
        
        success = success1 and success2
        
        if success:
            logger.info("=" * 60)
            logger.info("数据迁移完成")
            logger.info("=" * 60)
        else:
            logger.error("数据迁移部分失败，请检查日志")
        
        return success
    
    def verify_migration(self) -> bool:
        """
        验证迁移结果
        
        Returns:
            是否验证通过
        """
        logger.info("验证迁移结果...")
        
        try:
            # 验证registration_config
            config = self.db.execute_one(
                "SELECT config_value FROM registration_config WHERE config_key = 'current_index'"
            )
            if config:
                logger.info(f"✓ current_index 配置存在: {config['config_value']}")
            else:
                logger.warning("✗ current_index 配置不存在")
            
            # 验证registrations表
            reg_count = self.db.execute_one("SELECT COUNT(*) as count FROM registrations")
            if reg_count:
                logger.info(f"✓ registrations 表有 {reg_count['count']} 条记录")
            else:
                logger.warning("✗ registrations 表为空")
            
            # 验证z_params_cache表
            z_params = self.db.execute_query("SELECT param_key FROM z_params_cache")
            if z_params:
                logger.info(f"✓ z_params_cache 表有 {len(z_params)} 个参数")
            else:
                logger.warning("✗ z_params_cache 表为空")
            
            return True
            
        except Exception as e:
            logger.error(f"验证迁移结果失败: {e}", exc_info=True)
            return False


# 全局迁移实例
_migration_instance: Optional[DBMigration] = None


def get_migration(db_path: str = None) -> DBMigration:
    """
    获取全局迁移实例（单例模式）
    
    Args:
        db_path: 数据库文件路径（仅在首次调用时有效）
    
    Returns:
        DBMigration实例
    """
    global _migration_instance
    if _migration_instance is None:
        _migration_instance = DBMigration(db_path)
    return _migration_instance
