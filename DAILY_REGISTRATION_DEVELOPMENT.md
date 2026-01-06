# 每日账号注册功能开发文档

## 📋 项目概述

本文档用于审计和开发指导，描述在Docker环境中新增每日自动注册5个账号功能的开发计划。

## 🎯 功能需求

在Docker容器中新增一个定时任务，每天自动注册5个账号，并将注册结果保存到数据库中。

## 📝 需求分析

### 1. 当前状态

#### 1.1 现有注册脚本
- **位置**: `register/batch_register_jx2s0.py`
- **功能**: 批量注册 jx.2s0.cn 账号
- **特点**:
  - 使用Playwright进行浏览器自动化
  - 默认使用代理IP（`use_proxy=True`）
  - 当前保存到JSON文件（`registration_results.json`）
  - 使用系统Chrome浏览器（Windows环境）

#### 1.2 数据库结构
- **数据库路径**: `/app/data/video_parser.db` (Docker环境)
- **表名**: `registrations`
- **表结构**:
  ```sql
  CREATE TABLE registrations (
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
  ```

#### 1.3 Docker环境
- **基础镜像**: `python:3.11-slim`
- **工作目录**: `/app`
- **数据目录**: `/app/data` (挂载到宿主机)
- **已安装**: Playwright + Chromium浏览器
- **端口**: 8000 (内部)

### 2. 需要修改的点

#### 2.1 账号注册时不使用代理
- **当前**: 默认使用代理IP (`use_proxy=True`)
- **修改**: 在Docker环境中禁用代理，直接连接
- **原因**: Docker环境可能无法访问外部代理服务，且直连更稳定

#### 2.2 适配Docker运行环境
- **当前**: 使用系统Chrome浏览器（Windows路径）
- **修改**: 使用Playwright安装的Chromium浏览器
- **原因**: Docker环境中没有系统Chrome，需要使用Playwright的Chromium

#### 2.3 注册结果写入数据库
- **当前**: 保存到JSON文件 (`registration_results.json`)
- **修改**: 直接写入数据库 `registrations` 表
- **原因**: 统一数据存储方式，便于管理和查询

#### 2.4 添加定时任务
- **需求**: 每天自动执行一次，注册5个账号
- **实现**: 使用Python的定时任务库（如APScheduler）或cron

#### 2.5 添加测试接口
- **需求**: 提供HTTP接口，方便手动触发注册任务进行测试
- **实现**: 在FastAPI中添加注册接口

## 🔧 技术方案

### 1. 修改注册脚本适配Docker

#### 1.1 禁用代理
**文件**: `register/batch_register_jx2s0.py`

**修改点**:
- 在Docker环境中，默认设置 `use_proxy=False`
- 可以通过环境变量控制是否使用代理

**代码示例**:
```python
# 检测是否在Docker环境中
def is_docker_env():
    return Path("/app/data").exists() or os.path.exists("/.dockerenv")

# 在batch_register函数中
use_proxy = use_proxy and not is_docker_env()  # Docker环境禁用代理
```

#### 1.2 使用Playwright Chromium
**文件**: `register/batch_register_jx2s0.py`

**修改点**:
- 移除系统Chrome路径查找逻辑
- 在Docker环境中，直接使用Playwright的Chromium

**代码示例**:
```python
async def create_browser_context(playwright, use_proxy=False):
    """创建浏览器上下文（适配Docker环境）"""
    if is_docker_env():
        # Docker环境：使用Playwright的Chromium
        browser = await playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
    else:
        # 本地环境：使用系统Chrome（保持原有逻辑）
        # ... 原有代码 ...
    
    context_options = {
        'viewport': generate_random_viewport(),
        'user_agent': generate_random_user_agent(),
    }
    
    if use_proxy and proxy_config:
        context_options['proxy'] = proxy_config
    
    context = await browser.new_context(**context_options)
    await add_stealth_script(context)
    return context, browser
```

#### 1.3 写入数据库
**文件**: `register/batch_register_jx2s0.py`

**修改点**:
- 新增函数 `save_to_database()` 用于保存到数据库
- 修改 `save_single_result()` 函数，支持数据库保存

**代码示例**:
```python
def save_to_database(result: Dict) -> bool:
    """
    保存注册结果到数据库
    
    参数:
        result: 注册结果字典
    
    返回:
        是否保存成功
    """
    try:
        from utils.database import get_database
        
        db = get_database()
        
        # 检查是否已存在（基于email或uid）
        existing = db.execute_one(
            "SELECT id FROM registrations WHERE email = ? OR uid = ?",
            (result.get('email'), result.get('uid'))
        )
        
        if existing:
            # 更新现有记录
            db.execute_update(
                """
                UPDATE registrations 
                SET password = ?, uid = ?, "key" = ?, 
                    register_time = ?, expire_date = ?, 
                    updated_at = CURRENT_TIMESTAMP, is_active = 1
                WHERE email = ? OR uid = ?
                """,
                (
                    result.get('password'),
                    result.get('uid'),
                    result.get('key'),
                    result.get('register_time'),
                    result.get('expire_date'),
                    result.get('email'),
                    result.get('uid')
                )
            )
            logger.info(f"更新注册记录: {result.get('email')}")
        else:
            # 插入新记录
            db.execute_update(
                """
                INSERT INTO registrations 
                (email, password, uid, "key", register_time, expire_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.get('email'),
                    result.get('password'),
                    result.get('uid'),
                    result.get('key'),
                    result.get('register_time'),
                    result.get('expire_date'),
                    1  # is_active
                )
            )
            logger.info(f"新增注册记录: {result.get('email')}")
        
        return True
    except Exception as e:
        logger.error(f"保存到数据库失败: {e}", exc_info=True)
        return False

def save_single_result(result: Dict, filename: str = None, use_database: bool = True) -> bool:
    """
    保存单个注册结果（优先使用数据库）
    
    参数:
        result: 单个注册结果字典
        filename: JSON文件名（备用）
        use_database: 是否使用数据库（默认True）
    
    返回:
        是否保存成功
    """
    # 优先使用数据库
    if use_database:
        if save_to_database(result):
            return True
        else:
            logger.warning("数据库保存失败，降级到JSON文件")
    
    # 降级到JSON文件（保持兼容性）
    # ... 原有JSON保存逻辑 ...
```

### 2. 创建定时任务模块

#### 2.1 创建定时任务文件
**文件**: `tasks/daily_registration.py` (新建)

**功能**:
- 封装每日注册任务
- 使用APScheduler进行定时调度
- 记录任务执行日志

**代码结构**:
```python
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


async def daily_registration_task():
    """
    每日注册任务：注册指定数量的账号
    """
    logger.info("=" * 60)
    logger.info("开始执行每日注册任务")
    logger.info("=" * 60)
    
    try:
        # 从环境变量读取配置
        registration_count = int(os.getenv("DAILY_REGISTRATION_COUNT", "5"))
        registration_password = os.getenv("DAILY_REGISTRATION_PASSWORD", "qwer1234!")
        use_proxy_env = os.getenv("DAILY_REGISTRATION_USE_PROXY", "false").lower()
        use_proxy = use_proxy_env in ("true", "1", "yes")
        
        logger.info(f"注册配置: count={registration_count}, use_proxy={use_proxy}")
        
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
```

#### 2.2 在API服务中集成定时任务
**文件**: `api_server.py`

**修改点**:
- 在应用启动时启动定时任务调度器
- 确保任务在后台运行

**代码示例**:
```python
from tasks.daily_registration import start_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global paid_key_parser, z_param_parser, decrypt_parser, search_parser
    
    # ... 现有初始化代码 ...
    
    # 启动定时任务
    try:
        logger.info("启动定时任务调度器...")
        scheduler = start_scheduler()
        logger.info("定时任务调度器启动成功")
    except Exception as e:
        logger.error(f"定时任务调度器启动失败: {e}", exc_info=True)
    
    yield
    
    # 关闭时停止定时任务
    try:
        if 'scheduler' in locals():
            scheduler.shutdown()
            logger.info("定时任务调度器已关闭")
    except Exception as e:
        logger.error(f"关闭定时任务调度器失败: {e}", exc_info=True)
    
    logger.info("服务关闭")
```

### 3. 添加测试接口

#### 3.1 注册接口
**文件**: `api_server.py`

**新增接口**:
```python
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
        import asyncio
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
        from utils.database import get_database
        db = get_database()
        
        # 获取最近注册的账号数量
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
```

#### 3.2 查询注册记录接口
**文件**: `api_server.py`

**新增接口**:
```python
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
        from utils.database import get_database
        
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
```

### 4. 更新依赖文件

#### 4.1 requirements.txt
**文件**: `requirements.txt`

**新增依赖**:
```
APScheduler>=3.10.0  # 定时任务调度器
```

### 5. Docker配置

#### 5.1 docker-compose.yml
**文件**: `docker-compose.yml`

**无需修改**: 当前配置已满足需求

#### 5.2 环境变量配置
在 `docker-compose.yml` 中添加环境变量控制定时任务：

```yaml
environment:
  - TZ=Asia/Shanghai
  - API_BASE_URL=http://192.168.31.18:1233
  # 每日注册任务配置（可选，不设置则使用默认值）
  - DAILY_REGISTRATION_COUNT=5              # 每次注册数量（默认5，为空则默认5）
  - DAILY_REGISTRATION_PASSWORD=qwer1234!   # 注册密码（默认qwer1234!，为空则默认）
  - DAILY_REGISTRATION_USE_PROXY=false      # 是否使用代理（默认false，为空则默认关闭）
```

**环境变量说明**:
- `DAILY_REGISTRATION_COUNT`: 每次注册的账号数量，默认为5
- `DAILY_REGISTRATION_PASSWORD`: 注册时使用的密码，默认为 `qwer1234!`
- `DAILY_REGISTRATION_USE_PROXY`: 是否使用代理，可选值：`true`/`false`/`1`/`0`/`yes`/`no`，默认为 `false`（禁用代理）

**注意**: 
- 定时任务执行时间在每天凌晨0点到6点之间随机选择，无需配置
- 所有环境变量都是可选的，不设置则使用默认值

## 📋 开发任务清单

### 阶段1: 修改注册脚本适配Docker
- [ ] 1.1 修改 `batch_register_jx2s0.py`，添加Docker环境检测
- [ ] 1.2 修改浏览器启动逻辑，使用Playwright Chromium
- [ ] 1.3 在Docker环境中默认禁用代理
- [ ] 1.4 添加数据库保存功能 `save_to_database()`
- [ ] 1.5 修改 `save_single_result()` 支持数据库保存

### 阶段2: 创建定时任务模块
- [ ] 2.1 创建 `tasks/daily_registration.py` 文件
- [ ] 2.2 实现 `daily_registration_task()` 函数
- [ ] 2.3 实现 `start_scheduler()` 函数
- [ ] 2.4 在 `api_server.py` 中集成定时任务

### 阶段3: 添加测试接口
- [ ] 3.1 添加 `/api/v1/register` 接口（手动触发注册）
- [ ] 3.2 添加 `/api/v1/registrations` 接口（查询注册记录）
- [ ] 3.3 添加接口文档和错误处理

### 阶段4: 更新依赖和配置
- [ ] 4.1 更新 `requirements.txt`，添加APScheduler
- [ ] 4.2 测试Docker环境下的注册功能
- [ ] 4.3 测试定时任务执行

### 阶段5: 测试和验证
- [ ] 5.1 在Docker环境中测试单个注册
- [ ] 5.2 测试数据库保存功能
- [ ] 5.3 测试定时任务执行
- [ ] 5.4 测试API接口
- [ ] 5.5 验证日志记录

## ⚠️ 注意事项

### 1. 严禁编造代码
- 所有代码修改必须基于现有代码库
- 必须理解现有代码逻辑后再修改
- 不确定的地方要先沟通确认

### 2. Docker环境适配
- Docker环境中没有系统Chrome，必须使用Playwright的Chromium
- Docker环境可能无法访问外部代理服务，建议禁用代理
- 数据目录挂载在 `/app/data`，确保路径正确

### 3. 数据库操作
- 使用现有的 `utils.database` 模块
- 注意处理数据库锁定异常
- 确保事务正确提交

### 4. 定时任务
- 使用APScheduler的异步调度器
- 注意时区设置（Asia/Shanghai）
- 执行时间在每天凌晨0点到6点之间随机选择
- 确保任务异常不影响主服务
- 无需重试机制，失败后等待下次执行

### 5. 错误处理
- 注册失败不应影响服务运行
- 记录详细的错误日志（无需额外通知机制）
- 提供降级方案（数据库失败时降级到JSON）
- 无需重试机制，失败后等待下次定时执行

### 6. 测试建议
- 先在本地环境测试修改后的注册脚本
- 再在Docker环境中测试
- 测试时先手动触发，确认无误后再启用定时任务

## ✅ 已确认的配置

以下配置已经确认，将按照以下要求实现：

1. **定时任务执行时间**: ✅ 每天凌晨0点到6点之间随机时间执行
2. **注册数量**: ✅ 默认5个，可通过环境变量 `DAILY_REGISTRATION_COUNT` 自定义（为空则默认5个）
3. **密码策略**: ✅ 固定密码，可通过环境变量 `DAILY_REGISTRATION_PASSWORD` 自定义（为空则默认 `qwer1234!`）
4. **代理使用**: ✅ 默认禁用，可通过环境变量 `DAILY_REGISTRATION_USE_PROXY` 自定义（为空则默认关闭）
5. **失败重试**: ✅ 无需重试机制
6. **通知机制**: ✅ 不需要额外通知，记录日志即可

## 📚 参考文档

- [Playwright文档](https://playwright.dev/python/)
- [APScheduler文档](https://apscheduler.readthedocs.io/)
- [FastAPI文档](https://fastapi.tiangolo.com/)
- 项目现有代码：`register/batch_register_jx2s0.py`
- 项目现有代码：`utils/database.py`
- 项目现有代码：`api_server.py`

## 📝 更新日志

- 2024-XX-XX: 创建开发文档
- 2024-XX-XX: 确认配置需求
  - 定时任务执行时间：凌晨0点到6点随机
  - 注册数量：默认5个，可通过环境变量自定义
  - 密码：固定密码，可通过环境变量自定义
  - 代理：默认禁用，可通过环境变量自定义
  - 失败重试：无需重试
  - 通知机制：仅记录日志
