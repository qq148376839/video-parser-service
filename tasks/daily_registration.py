"""
每日账号注册定时任务
"""
import asyncio
import os
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.logger import logger
from register.batch_register_jx2s0 import batch_register
from clear_cache import clear_m3u8_cache_files


async def daily_registration_task():
    """
    每日注册任务：注册指定数量的账号
    """
    logger.info("=" * 60)
    logger.info("开始执行每日注册任务")
    logger.info("=" * 60)
    
    try:
        # 0. 清理m3u8缓存文件（不影响主流程）
        try:
            removed = clear_m3u8_cache_files(verbose=False)
            if removed > 0:
                logger.info(f"每日注册前已清理m3u8缓存文件: {removed} 个")
            else:
                logger.info("每日注册前m3u8缓存无需清理")
        except Exception as e:
            logger.warning(f"每日注册前清理m3u8缓存失败（忽略继续注册）: {e}")

        # 从环境变量读取配置
        registration_count = int(os.getenv("DAILY_REGISTRATION_COUNT", "5"))
        registration_password = os.getenv("DAILY_REGISTRATION_PASSWORD", "qwer1234!")
        use_proxy_env = os.getenv("DAILY_REGISTRATION_USE_PROXY", "false").lower()
        use_proxy = use_proxy_env in ("true", "1", "yes")
        
        logger.info(f"注册配置: count={registration_count}, password={'*' * len(registration_password)}, use_proxy={use_proxy}")
        
        # 执行注册
        await batch_register(
            count=registration_count, 
            password=registration_password, 
            use_proxy=use_proxy
        )
        
        logger.info("每日注册任务执行完成")
    except Exception as e:
        logger.error(f"每日注册任务执行失败: {e}", exc_info=True)


def get_random_schedule_time():
    """
    获取随机执行时间（凌晨0点到6点之间）
    
    返回:
        (hour, minute) 元组
    """
    hour = random.randint(0, 5)  # 0-5点
    minute = random.randint(0, 59)  # 0-59分
    return hour, minute


def start_scheduler():
    """
    启动定时任务调度器
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    
    # 每天凌晨0点到6点之间随机时间执行
    hour, minute = get_random_schedule_time()
    
    scheduler.add_job(
        daily_registration_task,
        trigger=CronTrigger(hour=hour, minute=minute),  # 随机时间执行
        id='daily_registration',
        name='每日账号注册任务',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("定时任务调度器已启动")
    logger.info(f"每日注册任务计划: 每天 {hour:02d}:{minute:02d} 执行")
    
    return scheduler
