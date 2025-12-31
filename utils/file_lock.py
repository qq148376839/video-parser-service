"""
文件锁工具模块
用于避免多线程/多进程访问JSON文件时的冲突
"""
import os
import time
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from utils.logger import logger

# Windows系统不支持fcntl，只在Unix/Linux系统导入
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    # Windows系统使用msvcrt作为替代
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False


class FileLock:
    """文件锁（支持Windows和Linux）"""
    
    @staticmethod
    @contextmanager
    def lock_file(file_path: Path, timeout: float = 5.0):
        """
        文件锁上下文管理器
        
        Args:
            file_path: 文件路径
            timeout: 超时时间（秒）
        
        Yields:
            文件对象
        """
        file_path = Path(file_path)
        lock_file_path = file_path.with_suffix(file_path.suffix + '.lock')
        
        start_time = time.time()
        lock_acquired = False
        
        lock_fd = None
        try:
            # Windows系统使用文件存在性检查或msvcrt
            if os.name == 'nt':
                if HAS_MSVCRT:
                    # 使用msvcrt进行文件锁定
                    while time.time() - start_time < timeout:
                        try:
                            lock_fd = os.open(str(lock_file_path), os.O_CREAT | os.O_RDWR)
                            # 尝试获取文件锁（非阻塞）
                            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                            lock_acquired = True
                            break
                        except (OSError, IOError):
                            # 锁文件已存在或被锁定，等待
                            if lock_fd:
                                try:
                                    os.close(lock_fd)
                                except:
                                    pass
                                lock_fd = None
                            time.sleep(0.1)
                            continue
                    
                    if not lock_acquired:
                        if lock_fd:
                            try:
                                os.close(lock_fd)
                            except:
                                pass
                        raise TimeoutError(f"获取文件锁超时: {file_path}")
                else:
                    # 回退到文件存在性检查
                    while time.time() - start_time < timeout:
                        try:
                            # 尝试创建锁文件（独占模式）
                            lock_fd = os.open(str(lock_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                            os.close(lock_fd)
                            lock_fd = None
                            lock_acquired = True
                            break
                        except OSError:
                            # 锁文件已存在，等待
                            if lock_fd:
                                try:
                                    os.close(lock_fd)
                                except:
                                    pass
                                lock_fd = None
                            time.sleep(0.1)
                            continue
                    
                    if not lock_acquired:
                        raise TimeoutError(f"获取文件锁超时: {file_path}")
            else:
                # Linux/Unix系统使用fcntl
                if HAS_FCNTL:
                    lock_fd = os.open(str(lock_file_path), os.O_CREAT | os.O_RDWR)
                    while time.time() - start_time < timeout:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            lock_acquired = True
                            break
                        except IOError:
                            time.sleep(0.1)
                            continue
                    
                    if not lock_acquired:
                        if lock_fd:
                            os.close(lock_fd)
                        raise TimeoutError(f"获取文件锁超时: {file_path}")
                else:
                    # 回退到文件存在性检查
                    while time.time() - start_time < timeout:
                        try:
                            lock_fd = os.open(str(lock_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                            os.close(lock_fd)
                            lock_fd = None
                            lock_acquired = True
                            break
                        except OSError:
                            if lock_fd:
                                try:
                                    os.close(lock_fd)
                                except:
                                    pass
                                lock_fd = None
                            time.sleep(0.1)
                            continue
                    
                    if not lock_acquired:
                        raise TimeoutError(f"获取文件锁超时: {file_path}")
            
            # 打开实际文件
            with open(file_path, 'r+', encoding='utf-8') as f:
                yield f
            
        finally:
            # 释放锁
            if lock_acquired:
                try:
                    if os.name == 'nt':
                        # Windows: 释放msvcrt锁或删除锁文件
                        if HAS_MSVCRT and lock_fd:
                            try:
                                msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                                os.close(lock_fd)
                            except:
                                pass
                        if lock_file_path.exists():
                            os.remove(lock_file_path)
                    else:
                        # Linux: 释放fcntl锁并关闭文件
                        if HAS_FCNTL and lock_fd:
                            try:
                                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                                os.close(lock_fd)
                            except:
                                pass
                        if lock_file_path.exists():
                            os.remove(lock_file_path)
                except Exception as e:
                    logger.debug(f"释放文件锁失败: {e}")
            elif lock_fd:
                # 如果获取锁失败，确保关闭文件描述符
                try:
                    os.close(lock_fd)
                except:
                    pass
