"""
FastAPI主服务
提供视频解析和资源检索API接口
"""
import time
import os
import threading
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from typing import Optional, Dict
from contextlib import asynccontextmanager
from urllib.parse import unquote

from utils.logger import logger, setup_logger
from utils.config_loader import config_loader
from utils.z_param_manager import z_param_manager
from utils.database import get_database
from utils.db_migration import get_migration
from utils.url_parse_cache import url_parse_cache
from parsers.paid_key_parser import PaidKeyParser
from parsers.z_param_parser import ZParamParser
from parsers.decrypt_parser import DecryptParser
from parsers.search_parser import SearchParser

# 设置日志
setup_logger("video_parser", log_file="api_server.log")

# 全局变量
app_start_time = time.time()
paid_key_parser = None
z_param_parser = None
decrypt_parser = None
search_parser = None

# 解析任务取消事件字典 {video_url: threading.Event}
_parse_cancellation_events: Dict[str, threading.Event] = {}
_parse_cancellation_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global paid_key_parser, z_param_parser, decrypt_parser, search_parser
    
    # 启动时初始化
    logger.info("=" * 60)
    logger.info("视频解析API服务启动")
    logger.info("=" * 60)
    
    # 1. 初始化数据库
    try:
        logger.info("初始化数据库...")
        db = get_database()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        logger.warning("服务将继续运行，但数据库功能可能不可用")
    
    # 2. 执行数据迁移（如果需要）
    try:
        logger.info("检查数据迁移...")
        migration = get_migration()
        
        # 检查是否需要迁移（如果JSON文件存在）
        from pathlib import Path
        if Path("/app/data").exists():
            data_dir = Path("/app/data")
        else:
            data_dir = Path("./data")
        
        registration_file = data_dir / "registration_results.json"
        z_params_file = data_dir / "z_params.json"
        
        if registration_file.exists() or z_params_file.exists():
            logger.info("检测到JSON文件，开始数据迁移...")
            if migration.migrate_all():
                logger.info("数据迁移完成")
                # 验证迁移结果
                migration.verify_migration()
            else:
                logger.warning("数据迁移部分失败，请检查日志")
        else:
            logger.info("未检测到JSON文件，跳过数据迁移")
            
    except Exception as e:
        logger.error(f"数据迁移失败: {e}", exc_info=True)
        logger.warning("服务将继续运行，但可能使用旧的数据格式")
    
    # 3. 获取API基础URL（从环境变量或使用默认值）
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # 4. 初始化解析器（按优先级顺序）
    # 注意：PaidKeyParser、ZParamParser和SearchParser需要API基础URL来生成本地m3u8接口链接
    paid_key_parser = PaidKeyParser(api_base_url=api_base_url)
    z_param_parser = ZParamParser(api_base_url=api_base_url)
    decrypt_parser = DecryptParser()
    search_parser = SearchParser(api_base_url=api_base_url)
    
    logger.info("所有解析器初始化完成")
    
    # 5. 启动定时任务
    scheduler = None
    try:
        logger.info("启动定时任务调度器...")
        from tasks.daily_registration import start_scheduler
        scheduler = start_scheduler()
        logger.info("定时任务调度器启动成功")
    except Exception as e:
        logger.error(f"定时任务调度器启动失败: {e}", exc_info=True)
        logger.warning("服务将继续运行，但定时任务功能可能不可用")
    
    logger.info("=" * 60)
    
    yield
    
    # 关闭时清理
    try:
        if scheduler:
            scheduler.shutdown()
            logger.info("定时任务调度器已关闭")
    except Exception as e:
        logger.error(f"关闭定时任务调度器失败: {e}", exc_info=True)
    
    logger.info("服务关闭")


# 创建FastAPI应用
app = FastAPI(
    title="视频解析API服务",
    description="提供视频解析和资源检索功能",
    version="1.0.0",
    lifespan=lifespan
)


# 注意：改为GET方法，使用Query参数，不再使用Pydantic模型


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "视频解析API服务",
        "version": "1.0.0",
        "endpoints": {
            "parse": "/api/v1/parse",
            "get_z_param": "/api/get_z_param",
            "search": "/api/v1/search",
            "m3u8": "/api/v1/m3u8/{file_id}",
            "health": "/health"
        }
    }


@app.get("/api/get_z_param")
async def get_z_param(
    video_url: str = Query(..., description="要解析的视频URL")
):
    """
    解析视频URL，返回m3u8链接（带缓存）
    
    Args:
        video_url: 要解析的视频URL（必填）
    
    Returns:
        解析结果，包含m3u8_url和解析方法
    
    示例：
        GET /api/get_z_param?video_url=https://v.youku.com/v_show/id_XMTA0MTc5NjU2.html
    """
    start_time = time.time()
    video_url = video_url.strip()
    
    # 验证URL格式
    if not video_url or not video_url.startswith(('http://', 'https://')):
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": "无效的视频URL格式，必须以http://或https://开头"
        }
    
    logger.info(f"收到解析请求: {video_url}")
    
    try:
        # 1. 检查缓存
        cache_result = url_parse_cache.get_cache(video_url)
        if cache_result:
            cache_time = time.time() - start_time
            logger.info(f"从缓存返回结果 (耗时: {cache_time:.3f}秒)")
            return {
                "success": True,
                "data": {
                    "m3u8_url": cache_result['m3u8_url'],
                    "method": cache_result.get('parse_method', 'unknown'),
                    "parse_time": round(cache_time, 3),
                    "cached": True
                }
            }
        
        # 2. 缓存未命中，执行解析
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # 使用线程池执行同步代码（兼容Python 3.8）
        try:
            # Python 3.7+推荐使用get_running_loop()
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 如果没有运行的事件循环，使用get_event_loop()（兼容旧版本）
            loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=3)
        
        # 先启动2s0解析，如果3秒后还在解析，再启动z参数解析
        logger.info("先启动2s0解析...")
        
        # 创建取消事件
        cancellation_event = threading.Event()
        with _parse_cancellation_lock:
            _parse_cancellation_events[video_url] = cancellation_event
        
        def parse_with_2s0_wrapper():
            """2s0解析包装函数，检查取消事件"""
            try:
                # 设置取消事件到解析器（如果支持）
                if hasattr(paid_key_parser, 'set_cancellation_event'):
                    paid_key_parser.set_cancellation_event(video_url, cancellation_event)
                return paid_key_parser.parse(video_url), "paid_key"
            except Exception as e:
                logger.error(f"2s0解析异常: {e}")
                return None, "paid_key"
            finally:
                # 清理取消事件
                with _parse_cancellation_lock:
                    _parse_cancellation_events.pop(video_url, None)
        
        def parse_with_z_param_wrapper():
            """z参数解析包装函数，检查取消事件"""
            try:
                # 设置取消事件到解析器（如果支持）
                if hasattr(z_param_parser, 'set_cancellation_event'):
                    z_param_parser.set_cancellation_event(video_url, cancellation_event)
                return z_param_parser.parse(video_url), "z_param"
            except Exception as e:
                logger.error(f"z参数解析异常: {e}")
                return None, "z_param"
            finally:
                # 清理取消事件
                with _parse_cancellation_lock:
                    _parse_cancellation_events.pop(video_url, None)
        
        async def parse_with_2s0():
            """2s0解析任务"""
            try:
                return await loop.run_in_executor(executor, parse_with_2s0_wrapper)
            except Exception as e:
                logger.error(f"2s0解析异常: {e}")
                return None, "paid_key"
        
        async def parse_with_z_param():
            """z参数解析任务"""
            try:
                return await loop.run_in_executor(executor, parse_with_z_param_wrapper)
            except Exception as e:
                logger.error(f"z参数解析异常: {e}")
                return None, "z_param"
        
        # 先启动2s0解析任务
        task_2s0 = asyncio.create_task(parse_with_2s0())
        task_z_param = None
        
        # 等待第一个成功的任务
        m3u8_url = None
        method = None
        fallback_used = False
        
        # 等待2s0解析完成，最多等待3秒
        try:
            done, pending = await asyncio.wait(
                [task_2s0],
                timeout=3.0,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 检查2s0是否已完成
            if done:
                for task in done:
                    result, method_name = await task
                    if result:
                        m3u8_url = result
                        method = method_name
                        logger.info(f"{method}解析器返回结果")
                        # 设置取消事件，中断其他解析器
                        cancellation_event.set()
                        # 清理取消事件
                        with _parse_cancellation_lock:
                            _parse_cancellation_events.pop(video_url, None)
                        # 如果2s0成功，直接返回（后续代码会处理缓存和返回）
                        break
                    else:
                        # 2s0完成但没有结果，启动z参数解析
                        logger.info("2s0解析完成但没有结果，启动z参数解析...")
                        task_z_param = asyncio.create_task(parse_with_z_param())
                        # 等待z参数解析完成
                        done_z, pending_z = await asyncio.wait(
                            [task_z_param],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        for task_z in done_z:
                            result_z, method_name_z = await task_z
                            if result_z:
                                m3u8_url = result_z
                                method = method_name_z
                                fallback_used = True
                                logger.info(f"{method}解析器返回结果")
                                cancellation_event.set()
                                break
                        break
            else:
                # 3秒后2s0还在解析，启动z参数解析
                logger.info("3秒后2s0还在解析，启动z参数解析...")
                task_z_param = asyncio.create_task(parse_with_z_param())
                
                # 等待任一任务完成
                done, pending = await asyncio.wait(
                    [task_2s0, task_z_param],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 检查已完成的任务
                for task in done:
                    result, method_name = await task
                    if result:
                        m3u8_url = result
                        method = method_name
                        if method == "z_param":
                            fallback_used = True
                        logger.info(f"{method}解析器最先返回结果")
                        # 设置取消事件，中断其他解析器
                        cancellation_event.set()
                        # 取消其他未完成的任务
                        for p in pending:
                            p.cancel()
                            try:
                                await p
                            except asyncio.CancelledError:
                                pass
                        break
                
                # 如果第一个完成的任务没有结果，等待其他任务完成
                if not m3u8_url and pending:
                    # 等待剩余任务完成
                    done_remaining, _ = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
                    # 只检查新完成的任务（之前done中的任务已经检查过了）
                    for task in done_remaining:
                        try:
                            result, method_name = await task
                            if result:
                                m3u8_url = result
                                method = method_name
                                if method == "z_param":
                                    fallback_used = True
                                logger.info(f"{method}解析器返回结果")
                                # 设置取消事件，中断其他解析器
                                cancellation_event.set()
                                break
                        except Exception as e:
                            logger.debug(f"任务异常: {e}")
                            continue
        except asyncio.TimeoutError:
            # 3秒超时，启动z参数解析
            logger.info("3秒后2s0还在解析，启动z参数解析...")
            task_z_param = asyncio.create_task(parse_with_z_param())
            
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [task_2s0, task_z_param],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 检查已完成的任务
            for task in done:
                result, method_name = await task
                if result:
                    m3u8_url = result
                    method = method_name
                    if method == "z_param":
                        fallback_used = True
                    logger.info(f"{method}解析器最先返回结果")
                    # 设置取消事件，中断其他解析器
                    cancellation_event.set()
                    # 取消其他未完成的任务
                    for p in pending:
                        p.cancel()
                        try:
                            await p
                        except asyncio.CancelledError:
                            pass
                    break
            
            # 如果第一个完成的任务没有结果，等待其他任务完成
            if not m3u8_url and pending:
                # 等待剩余任务完成
                done_remaining, _ = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
                # 只检查新完成的任务（之前done中的任务已经检查过了）
                for task in done_remaining:
                    try:
                        result, method_name = await task
                        if result:
                            m3u8_url = result
                            method = method_name
                            if method == "z_param":
                                fallback_used = True
                            logger.info(f"{method}解析器返回结果")
                            # 设置取消事件，中断其他解析器
                            cancellation_event.set()
                            break
                    except Exception as e:
                        logger.debug(f"任务异常: {e}")
                        continue
        
        # 清理取消事件（如果还没有被清理）
        with _parse_cancellation_lock:
            _parse_cancellation_events.pop(video_url, None)
        
        # 如果2s0和z参数都失败，尝试解密解析
        if not m3u8_url:
            logger.info("2s0和z参数解析都失败，切换到解密方案")
            m3u8_url = await loop.run_in_executor(executor, decrypt_parser.parse, "https://jx.789jiexi.com", video_url)
            method = "decrypt"
            fallback_used = True
        
        parse_time = time.time() - start_time
        
        if m3u8_url:
            # 3. 保存到缓存
            # 提取file_id（如果m3u8_url是本地API接口）
            file_id = None
            m3u8_file_path = None
            if '/api/v1/m3u8/' in m3u8_url:
                file_id = m3u8_url.split('/api/v1/m3u8/')[-1]
                # 获取m3u8文件路径（优先从对应解析器获取）
                if method == "paid_key" and paid_key_parser:
                    m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
                elif method == "z_param" and z_param_parser:
                    m3u8_file_path = z_param_parser.get_m3u8_file_path(file_id)
                else:
                    # 尝试从两个解析器都查找
                    if paid_key_parser:
                        m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
                    if not m3u8_file_path and z_param_parser:
                        m3u8_file_path = z_param_parser.get_m3u8_file_path(file_id)
            
            url_parse_cache.save_cache(
                video_url=video_url,
                m3u8_url=m3u8_url,
                m3u8_file_path=m3u8_file_path,
                file_id=file_id,
                parse_method=method
            )
            
            logger.info(f"解析成功 ({method}): {m3u8_url[:100]}... (耗时: {parse_time:.2f}秒)")
            return {
                "success": True,
                "data": {
                    "m3u8_url": m3u8_url,
                    "method": method,
                    "parse_time": round(parse_time, 2),
                    "cached": False
                },
                "fallback_used": fallback_used
            }
        else:
            logger.warning(f"解析失败 (耗时: {parse_time:.2f}秒)")
            return {
                "success": False,
                "data": {},
                "error": "所有解析方案都失败",
                "fallback_used": fallback_used
            }
            
    except Exception as e:
        logger.error(f"解析异常: {e}", exc_info=True)
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"解析失败: {str(e)}"
        }


@app.get("/api/v1/parse")
async def parse_video(
    url: str = Query(..., description="要解析的视频URL"),
    parser_url: Optional[str] = Query("https://jx.789jiexi.com", description="解析网站URL（可选）")
):
    """
    解析视频URL，返回m3u8链接（带缓存）
    
    Args:
        url: 要解析的视频URL（必填）
        parser_url: 解析网站URL（可选，默认https://jx.789jiexi.com）
    
    Returns:
        解析结果，包含m3u8_url和解析方法
    
    示例：
        GET /api/v1/parse?url=https://www.iqiyi.com/v_xxx.html&parser_url=https://jx.789jiexi.com
    """
    start_time = time.time()
    video_url = url.strip()
    
    # 验证URL格式
    if not video_url or not video_url.startswith(('http://', 'https://')):
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": "无效的视频URL格式，必须以http://或https://开头"
        }
    
    logger.info(f"收到解析请求: {video_url}")
    
    try:
        # 1. 检查缓存
        cache_result = url_parse_cache.get_cache(video_url)
        if cache_result:
            cache_time = time.time() - start_time
            logger.info(f"从缓存返回结果 (耗时: {cache_time:.3f}秒)")
            return {
                "success": True,
                "data": {
                    "m3u8_url": cache_result['m3u8_url'],
                    "method": cache_result.get('parse_method', 'unknown'),
                    "parse_time": round(cache_time, 3),
                    "cached": True
                }
            }
        
        # 2. 缓存未命中，执行解析
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # 使用线程池执行同步代码（兼容Python 3.8）
        try:
            # Python 3.7+推荐使用get_running_loop()
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 如果没有运行的事件循环，使用get_event_loop()（兼容旧版本）
            loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=3)
        
        # 先启动2s0解析，如果3秒后还在解析，再启动z参数解析
        logger.info("先启动2s0解析...")
        
        # 创建取消事件
        cancellation_event = threading.Event()
        with _parse_cancellation_lock:
            _parse_cancellation_events[video_url] = cancellation_event
        
        def parse_with_2s0_wrapper():
            """2s0解析包装函数，检查取消事件"""
            try:
                # 设置取消事件到解析器（如果支持）
                if hasattr(paid_key_parser, 'set_cancellation_event'):
                    paid_key_parser.set_cancellation_event(video_url, cancellation_event)
                return paid_key_parser.parse(video_url), "paid_key"
            except Exception as e:
                logger.error(f"2s0解析异常: {e}")
                return None, "paid_key"
            finally:
                # 清理取消事件
                with _parse_cancellation_lock:
                    _parse_cancellation_events.pop(video_url, None)
        
        def parse_with_z_param_wrapper():
            """z参数解析包装函数，检查取消事件"""
            try:
                # 设置取消事件到解析器（如果支持）
                if hasattr(z_param_parser, 'set_cancellation_event'):
                    z_param_parser.set_cancellation_event(video_url, cancellation_event)
                return z_param_parser.parse(video_url), "z_param"
            except Exception as e:
                logger.error(f"z参数解析异常: {e}")
                return None, "z_param"
            finally:
                # 清理取消事件
                with _parse_cancellation_lock:
                    _parse_cancellation_events.pop(video_url, None)
        
        async def parse_with_2s0():
            """2s0解析任务"""
            try:
                return await loop.run_in_executor(executor, parse_with_2s0_wrapper)
            except Exception as e:
                logger.error(f"2s0解析异常: {e}")
                return None, "paid_key"
        
        async def parse_with_z_param():
            """z参数解析任务"""
            try:
                return await loop.run_in_executor(executor, parse_with_z_param_wrapper)
            except Exception as e:
                logger.error(f"z参数解析异常: {e}")
                return None, "z_param"
        
        # 先启动2s0解析任务
        task_2s0 = asyncio.create_task(parse_with_2s0())
        task_z_param = None
        
        # 等待第一个成功的任务
        m3u8_url = None
        method = None
        fallback_used = False
        
        # 等待2s0解析完成，最多等待3秒
        try:
            done, pending = await asyncio.wait(
                [task_2s0],
                timeout=3.0,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 检查2s0是否已完成
            if done:
                for task in done:
                    result, method_name = await task
                    if result:
                        m3u8_url = result
                        method = method_name
                        logger.info(f"{method}解析器返回结果")
                        # 设置取消事件，中断其他解析器
                        cancellation_event.set()
                        # 清理取消事件
                        with _parse_cancellation_lock:
                            _parse_cancellation_events.pop(video_url, None)
                        # 如果2s0成功，直接返回（后续代码会处理缓存和返回）
                        break
                    else:
                        # 2s0完成但没有结果，启动z参数解析
                        logger.info("2s0解析完成但没有结果，启动z参数解析...")
                        task_z_param = asyncio.create_task(parse_with_z_param())
                        # 等待z参数解析完成
                        done_z, pending_z = await asyncio.wait(
                            [task_z_param],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        for task_z in done_z:
                            result_z, method_name_z = await task_z
                            if result_z:
                                m3u8_url = result_z
                                method = method_name_z
                                fallback_used = True
                                logger.info(f"{method}解析器返回结果")
                                cancellation_event.set()
                                break
                        break
            else:
                # 3秒后2s0还在解析，启动z参数解析
                logger.info("3秒后2s0还在解析，启动z参数解析...")
                task_z_param = asyncio.create_task(parse_with_z_param())
                
                # 等待任一任务完成
                done, pending = await asyncio.wait(
                    [task_2s0, task_z_param],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 检查已完成的任务
                for task in done:
                    result, method_name = await task
                    if result:
                        m3u8_url = result
                        method = method_name
                        if method == "z_param":
                            fallback_used = True
                        logger.info(f"{method}解析器最先返回结果")
                        # 设置取消事件，中断其他解析器
                        cancellation_event.set()
                        # 取消其他未完成的任务
                        for p in pending:
                            p.cancel()
                            try:
                                await p
                            except asyncio.CancelledError:
                                pass
                        break
                
                # 如果第一个完成的任务没有结果，等待其他任务完成
                if not m3u8_url and pending:
                    # 等待剩余任务完成
                    done_remaining, _ = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
                    # 只检查新完成的任务（之前done中的任务已经检查过了）
                    for task in done_remaining:
                        try:
                            result, method_name = await task
                            if result:
                                m3u8_url = result
                                method = method_name
                                if method == "z_param":
                                    fallback_used = True
                                logger.info(f"{method}解析器返回结果")
                                # 设置取消事件，中断其他解析器
                                cancellation_event.set()
                                break
                        except Exception as e:
                            logger.debug(f"任务异常: {e}")
                            continue
        except asyncio.TimeoutError:
            # 3秒超时，启动z参数解析
            logger.info("3秒后2s0还在解析，启动z参数解析...")
            task_z_param = asyncio.create_task(parse_with_z_param())
            
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [task_2s0, task_z_param],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 检查已完成的任务
            for task in done:
                result, method_name = await task
                if result:
                    m3u8_url = result
                    method = method_name
                    if method == "z_param":
                        fallback_used = True
                    logger.info(f"{method}解析器最先返回结果")
                    # 设置取消事件，中断其他解析器
                    cancellation_event.set()
                    # 取消其他未完成的任务
                    for p in pending:
                        p.cancel()
                        try:
                            await p
                        except asyncio.CancelledError:
                            pass
                    break
            
            # 如果第一个完成的任务没有结果，等待其他任务完成
            if not m3u8_url and pending:
                # 等待剩余任务完成
                done_remaining, _ = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
                # 只检查新完成的任务（之前done中的任务已经检查过了）
                for task in done_remaining:
                    try:
                        result, method_name = await task
                        if result:
                            m3u8_url = result
                            method = method_name
                            if method == "z_param":
                                fallback_used = True
                            logger.info(f"{method}解析器返回结果")
                            # 设置取消事件，中断其他解析器
                            cancellation_event.set()
                            break
                    except Exception as e:
                        logger.debug(f"任务异常: {e}")
                        continue
        
        # 清理取消事件（如果还没有被清理）
        with _parse_cancellation_lock:
            _parse_cancellation_events.pop(video_url, None)
        
        # 如果2s0和z参数都失败，尝试解密解析
        if not m3u8_url:
            logger.info("2s0和z参数解析都失败，切换到解密方案")
            m3u8_url = await loop.run_in_executor(executor, decrypt_parser.parse, parser_url, video_url)
            method = "decrypt"
            fallback_used = True
        
        parse_time = time.time() - start_time
        
        if m3u8_url:
            # 3. 保存到缓存
            # 提取file_id（如果m3u8_url是本地API接口）
            file_id = None
            m3u8_file_path = None
            if '/api/v1/m3u8/' in m3u8_url:
                file_id = m3u8_url.split('/api/v1/m3u8/')[-1]
                # 获取m3u8文件路径（优先从对应解析器获取）
                if method == "paid_key" and paid_key_parser:
                    m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
                elif method == "z_param" and z_param_parser:
                    m3u8_file_path = z_param_parser.get_m3u8_file_path(file_id)
                else:
                    # 尝试从两个解析器都查找
                    if paid_key_parser:
                        m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
                    if not m3u8_file_path and z_param_parser:
                        m3u8_file_path = z_param_parser.get_m3u8_file_path(file_id)
            
            url_parse_cache.save_cache(
                video_url=video_url,
                m3u8_url=m3u8_url,
                m3u8_file_path=m3u8_file_path,
                file_id=file_id,
                parse_method=method
            )
            
            logger.info(f"解析成功 ({method}): {m3u8_url[:100]}... (耗时: {parse_time:.2f}秒)")
            return {
                "success": True,
                "data": {
                    "m3u8_url": m3u8_url,
                    "method": method,
                    "parse_time": round(parse_time, 2),
                    "cached": False
                },
                "fallback_used": fallback_used
            }
        else:
            logger.warning(f"解析失败 (耗时: {parse_time:.2f}秒)")
            return {
                "success": False,
                "data": {},
                "error": "所有解析方案都失败",
                "fallback_used": fallback_used
            }
            
    except Exception as e:
        logger.error(f"解析异常: {e}", exc_info=True)
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"解析失败: {str(e)}"
        }


@app.get("/api/v1/search")
async def search_videos(
    ac: str = Query("videolist", description="固定值：videolist"),
    wd: str = Query(..., description="搜索关键词（必填）"),
    page: Optional[int] = Query(1, description="页码（可选，默认1）")
):
    """
    搜索资源并解析视频地址
    
    Args:
        ac: 固定值 "videolist"
        wd: 搜索关键词（必填）
        page: 页码（可选，默认1）
    
    Returns:
        搜索结果，包含解析后的m3u8地址
    
    示例：
        GET /api/v1/search?ac=videolist&wd=新僵尸先生&page=1
    """
    start_time = time.time()
    
    # 验证ac参数
    if ac != "videolist":
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"参数ac必须为'videolist'，当前值: {ac}"
        }
    
    keyword = unquote(wd).strip()  # URL解码关键词并去除空格
    
    logger.info(f"收到搜索请求: {keyword} (页码: {page})")
    
    if not keyword:
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": "关键词不能为空"
        }
    
    try:
        result = search_parser.search_and_parse(keyword)
        
        search_time = time.time() - start_time
        logger.info(f"搜索完成 (耗时: {search_time:.2f}秒, 结果数: {result.get('total', 0)})")
        
        return result
        
    except Exception as e:
        logger.error(f"搜索异常: {e}", exc_info=True)
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"搜索失败: {str(e)}"
        }


@app.get("/api/v1/m3u8/{file_id}")
async def get_m3u8_file(file_id: str, request: Request):
    """
    获取下载的m3u8文件内容或其他缓存文件（如enc.key）
    
    Args:
        file_id: 文件ID（由2s0解析器或z参数解析器生成）或文件名（如enc.key）
        request: FastAPI请求对象
    
    Returns:
        文件内容（根据文件类型返回相应的Content-Type）
    """
    m3u8_file_path = None
    
    # 首先尝试从2s0解析器获取
    if paid_key_parser:
        m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
    
    # 如果2s0解析器没有找到，尝试从z参数解析器获取
    if not m3u8_file_path and z_param_parser:
        m3u8_file_path = z_param_parser.get_m3u8_file_path(file_id)
    
    # 如果通过解析器没有找到，尝试直接从m3u8_cache目录查找文件
    if not m3u8_file_path:
        project_root = Path(__file__).parent
        cache_dir = project_root / "data" / "m3u8_cache"
        # 尝试直接查找文件（支持文件名如enc.key）
        direct_file_path = cache_dir / file_id
        if direct_file_path.exists() and direct_file_path.is_file():
            m3u8_file_path = str(direct_file_path)
            logger.info(f"从m3u8_cache目录找到文件: {file_id}")
    
    if not m3u8_file_path:
        logger.warning(f"请求的文件不存在: file_id={file_id}")
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"m3u8文件不存在: {file_id}"
        }
    
    # 检查文件是否存在
    if not os.path.exists(m3u8_file_path):
        logger.error(f"文件路径不存在: {m3u8_file_path}")
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": "m3u8文件不存在"
        }
    
    try:
        # 根据文件扩展名判断文件类型
        file_path_obj = Path(m3u8_file_path)
        file_ext = file_path_obj.suffix.lower()
        
        # 判断是否为二进制文件（如.key文件）
        binary_extensions = {'.key', '.bin', '.dat'}
        is_binary = file_ext in binary_extensions
        
        if is_binary:
            # 读取二进制文件
            with open(m3u8_file_path, 'rb') as f:
                content = f.read()
            
            logger.debug(f"返回二进制文件: file_id={file_id}, 大小={len(content)} 字节")
            
            # 根据文件扩展名设置Content-Type
            content_type_map = {
                '.key': 'application/octet-stream',
                '.bin': 'application/octet-stream',
                '.dat': 'application/octet-stream'
            }
            content_type = content_type_map.get(file_ext, 'application/octet-stream')
            
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="{file_id}"',
                    "Cache-Control": "no-cache"
                }
            )
        else:
            # 读取文本文件（m3u8文件）
            with open(m3u8_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            logger.debug(f"返回m3u8文件: file_id={file_id}, 大小={len(content)} 字节")
            
            # 返回文件内容，设置正确的Content-Type
            return PlainTextResponse(
                content=content,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Content-Disposition": f'inline; filename="{file_id}"',
                    "Cache-Control": "no-cache"
                }
            )
    except Exception as e:
        logger.error(f"读取文件失败: {e}", exc_info=True)
        return {
            "success": False,
            "data": {},
            "fallback_used": False,
            "error": f"读取文件失败: {str(e)}"
        }


@app.post("/api/v1/register")
async def trigger_registration(
    count: int = Query(5, ge=1, le=20, description="注册数量（1-20）"),
    password: str = Query("qwer1234!", description="注册密码"),
    use_proxy: bool = Query(False, description="是否使用代理（Docker环境建议False）")
):
    """
    手动触发账号注册任务（用于测试）
    
    Args:
        count: 注册数量（1-20，默认5）
        password: 注册密码（默认qwer1234!）
        use_proxy: 是否使用代理（Docker环境建议False）
    
    Returns:
        注册结果统计
    """
    logger.info(f"收到手动注册请求: count={count}, use_proxy={use_proxy}")
    
    try:
        from register.batch_register_jx2s0 import batch_register
        
        # 在后台执行注册任务
        task = asyncio.create_task(batch_register(count=count, password=password, use_proxy=use_proxy))
        
        # 等待任务完成（设置超时）
        try:
            await asyncio.wait_for(task, timeout=300)  # 5分钟超时
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "注册任务超时（超过5分钟）"
            }
        
        # 查询注册结果
        db = get_database()
        
        # 获取最近注册的账号数量（最近1小时内）
        recent_registrations = db.execute_query(
            """
            SELECT COUNT(*) as count 
            FROM registrations 
            WHERE created_at > datetime('now', '-1 hour')
            """
        )
        
        return {
            "success": True,
            "message": f"注册任务已完成，请求注册 {count} 个账号",
            "recent_registrations": recent_registrations[0]['count'] if recent_registrations else 0
        }
        
    except Exception as e:
        logger.error(f"手动注册任务失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"注册任务失败: {str(e)}"
        }


@app.get("/api/v1/registrations")
async def get_registrations(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    is_active: Optional[bool] = Query(None, description="是否激活（可选）")
):
    """
    查询注册记录列表
    
    Args:
        page: 页码（从1开始）
        page_size: 每页数量（1-100）
        is_active: 是否激活（可选，None表示全部）
    
    Returns:
        注册记录列表和分页信息
    """
    try:
        db = get_database()
        
        # 构建查询条件
        where_clause = ""
        params = []
        
        if is_active is not None:
            where_clause = "WHERE is_active = ?"
            params.append(1 if is_active else 0)
        
        # 查询总数
        count_query = f"SELECT COUNT(*) as count FROM registrations {where_clause}"
        total = db.execute_one(count_query, tuple(params))
        total_count = total['count'] if total else 0
        
        # 查询分页数据
        offset = (page - 1) * page_size
        query = f"""
            SELECT id, email, uid, register_time, expire_date, 
                   created_at, updated_at, is_active
            FROM registrations 
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([page_size, offset])
        
        registrations = db.execute_query(query, tuple(params))
        
        return {
            "success": True,
            "data": {
                "items": registrations,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total_count,
                    "total_pages": (total_count + page_size - 1) // page_size
                }
            }
        }
        
    except Exception as e:
        logger.error(f"查询注册记录失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"查询失败: {str(e)}"
        }


@app.get("/health")
async def health_check():
    """
    健康检查接口
    
    Returns:
        服务健康状态
    """
    uptime = int(time.time() - app_start_time)
    z_param_status = "valid" if not z_param_manager.is_expired() else "expired"
    z_param_age = z_param_manager.get_age_seconds()
    
    status = "healthy"
    if z_param_status == "expired":
        status = "degraded"
    
    return {
        "status": status,
        "z_param_status": z_param_status,
        "z_param_age": z_param_age,
        "uptime": uptime
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        log_level="debug",
        reload=False
    )

