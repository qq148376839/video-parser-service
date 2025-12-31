"""
FastAPI主服务
提供视频解析和资源检索API接口
"""
import time
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from typing import Optional
from contextlib import asynccontextmanager
from urllib.parse import unquote

from utils.logger import logger, setup_logger
from utils.config_loader import config_loader
from utils.z_param_manager import z_param_manager
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global paid_key_parser, z_param_parser, decrypt_parser, search_parser
    
    # 启动时初始化
    logger.info("=" * 60)
    logger.info("视频解析API服务启动")
    logger.info("=" * 60)
    
    # 获取API基础URL（从环境变量或使用默认值）
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # 初始化解析器（按优先级顺序）
    # 注意：PaidKeyParser需要API基础URL来生成本地m3u8接口链接
    paid_key_parser = PaidKeyParser(api_base_url=api_base_url)
    z_param_parser = ZParamParser()
    decrypt_parser = DecryptParser()
    search_parser = SearchParser()
    
    logger.info("所有解析器初始化完成")
    logger.info("=" * 60)
    
    yield
    
    # 关闭时清理
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
            "search": "/api/v1/search",
            "m3u8": "/api/v1/m3u8/{file_id}",
            "health": "/health"
        }
    }


@app.get("/api/v1/parse")
async def parse_video(
    url: str = Query(..., description="要解析的视频URL"),
    parser_url: Optional[str] = Query("https://jx.789jiexi.com", description="解析网站URL（可选）")
):
    """
    解析视频URL，返回m3u8链接
    
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
        raise HTTPException(status_code=400, detail="无效的视频URL格式，必须以http://或https://开头")
    
    logger.info(f"收到解析请求: {video_url}")
    
    try:
        import asyncio
        
        # 优先级1: 2s0解析（在线程中运行，避免阻塞事件循环）
        m3u8_url = await asyncio.to_thread(paid_key_parser.parse, video_url)
        method = "paid_key"
        fallback_used = False
        
        # 优先级2: z参数解析
        if not m3u8_url:
            logger.info("2s0解析方案失败，切换到z参数方案")
            m3u8_url = await asyncio.to_thread(z_param_parser.parse, video_url)
            method = "z_param"
            fallback_used = True
        
        # 优先级3: 解密解析
        if not m3u8_url:
            logger.info("z参数方案失败，切换到解密方案")
            m3u8_url = await asyncio.to_thread(decrypt_parser.parse, parser_url, video_url)
            method = "decrypt"
            fallback_used = True
        
        parse_time = time.time() - start_time
        
        if m3u8_url:
            logger.info(f"解析成功 ({method}): {m3u8_url[:100]}... (耗时: {parse_time:.2f}秒)")
            return {
                "success": True,
                "data": {
                    "m3u8_url": m3u8_url,
                    "method": method,
                    "parse_time": round(parse_time, 2)
                },
                "fallback_used": fallback_used
            }
        else:
            logger.warning(f"解析失败 (耗时: {parse_time:.2f}秒)")
            return {
                "success": False,
                "error": "所有解析方案都失败",
                "fallback_used": fallback_used
            }
            
    except Exception as e:
        logger.error(f"解析异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


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
        raise HTTPException(status_code=400, detail=f"参数ac必须为'videolist'，当前值: {ac}")
    
    keyword = unquote(wd).strip()  # URL解码关键词并去除空格
    
    logger.info(f"收到搜索请求: {keyword} (页码: {page})")
    
    if not keyword:
        raise HTTPException(status_code=400, detail="关键词不能为空")
    
    try:
        result = search_parser.search_and_parse(keyword)
        
        search_time = time.time() - start_time
        logger.info(f"搜索完成 (耗时: {search_time:.2f}秒, 结果数: {result.get('total', 0)})")
        
        return result
        
    except Exception as e:
        logger.error(f"搜索异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@app.get("/api/v1/m3u8/{file_id}")
async def get_m3u8_file(file_id: str, request: Request):
    """
    获取下载的m3u8文件内容
    
    Args:
        file_id: 文件ID（由2s0解析器生成）
        request: FastAPI请求对象
    
    Returns:
        m3u8文件内容（text/plain格式）
    """
    if not paid_key_parser:
        raise HTTPException(status_code=503, detail="2s0解析器未初始化")
    
    # 获取m3u8文件路径
    m3u8_file_path = paid_key_parser.get_m3u8_file_path(file_id)
    
    if not m3u8_file_path:
        logger.warning(f"请求的m3u8文件不存在: file_id={file_id}")
        raise HTTPException(status_code=404, detail=f"m3u8文件不存在: {file_id}")
    
    # 检查文件是否存在
    if not os.path.exists(m3u8_file_path):
        logger.error(f"m3u8文件路径不存在: {m3u8_file_path}")
        raise HTTPException(status_code=404, detail="m3u8文件不存在")
    
    try:
        # 读取文件内容
        with open(m3u8_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        logger.debug(f"返回m3u8文件: file_id={file_id}, 大小={len(content)} 字节")
        
        # 返回文件内容，设置正确的Content-Type
        return PlainTextResponse(
            content=content,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Content-Disposition": f'inline; filename="{file_id}.m3u8"',
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        logger.error(f"读取m3u8文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取m3u8文件失败: {str(e)}")


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
        log_level="info",
        reload=False
    )

