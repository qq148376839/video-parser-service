# 视频解析服务 - 数据库集成与搜索缓存项目规划文档

## 一、项目背景

### 1.1 当前状态
- **数据存储方式**：使用JSON文件存储数据
  - `data/registration_results.json` - 存储2s0 key注册信息
  - `data/z_params.json` - 存储z参数缓存
  - `data/m3u8_cache/` - 存储M3U8文件
- **搜索流程**：每次搜索都会调用API站点，然后解析所有视频URL，耗时较长
- **数据库文件**：已存在 `data/video_parser.db`，包含 `search_cache` 和 `registrations` 表结构，但未集成到代码中

### 1.2 需求目标
1. **搜索缓存**：第一次搜索后建立索引，下次搜索相同关键词时直接返回缓存结果，避免重复解析
2. **数据库迁移**：将JSON文件数据迁移到数据库，统一数据管理
3. **数据持久化**：Docker部署时数据不丢失，项目更新时数据保留
4. **本地测试**：提供完整的本地测试方案

### 1.3 搜索缓存的作用说明

**当前搜索流程（无缓存时）：**
1. 用户搜索关键词（如"新僵尸先生"）
2. **步骤1**：并发调用多个API站点搜索（网络请求，超时5秒，可能耗时3-5秒）
3. **步骤2**：合并去重搜索结果
4. **步骤3**：对每个视频的每个URL进行解析（调用解析器，可能需要多次网络请求）
   - 单集视频：需要解析1个URL
   - 多集视频：需要并发解析多个URL（可能10-50个），每个URL可能需要3-10秒
   - **总耗时可能达到10-60秒甚至更长**
5. 返回最终结果

**搜索缓存的作用：**
- **缓存整个搜索和解析流程的最终结果**（步骤1-4的完整结果）
- 当用户再次搜索相同关键词时，**直接返回缓存的结果**，跳过步骤1-4
- **性能提升**：从10-60秒降低到<100ms（数据库查询时间）
- **减少API调用**：避免重复调用外部API站点
- **减少解析开销**：避免重复解析视频URL

**示例场景：**
- 用户A搜索"新僵尸先生" → 执行完整流程，耗时30秒，结果缓存
- 用户B搜索"新僵尸先生" → 直接返回缓存，耗时50ms
- 用户A再次搜索"新僵尸先生" → 直接返回缓存，耗时50ms

## 二、技术方案设计

### 2.1 数据库选择

**选择SQLite的原因：**
- ✅ 轻量级，无需额外服务
- ✅ 文件数据库，易于备份和迁移
- ✅ 支持JSON字段存储（SQLite 3.38+）
- ✅ 适合单机部署场景
- ✅ 已有数据库文件基础

**数据库文件位置：**
- 本地开发：`data/video_parser.db`
- Docker部署：`/app/data/video_parser.db`（通过volume挂载）

### 2.2 数据库表结构设计

#### 2.2.1 搜索缓存表（search_cache）
```sql
CREATE TABLE IF NOT EXISTS search_cache (
    keyword VARCHAR(255) PRIMARY KEY,           -- 搜索关键词（主键）
    results JSON NOT NULL,                       -- 搜索结果（JSON格式）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 更新时间
    expire_at DATETIME,                          -- 过期时间（可选）
    hit_count INTEGER DEFAULT 0                  -- 命中次数（统计用）
);

CREATE INDEX IF NOT EXISTS ix_search_cache_keyword ON search_cache(keyword);
CREATE INDEX IF NOT EXISTS ix_search_cache_updated_at ON search_cache(updated_at);
CREATE INDEX IF NOT EXISTS ix_search_cache_expire_at ON search_cache(expire_at);
```

**字段说明：**
- `keyword`: 搜索关键词，作为主键确保唯一性
- `results`: 完整的搜索结果JSON（包含code, msg, page, total, list等）
- `created_at`: 首次创建时间
- `updated_at`: 最后更新时间（用于判断缓存是否过期）
- `expire_at`: 过期时间（可选，用于自动清理过期缓存）
- `hit_count`: 命中次数，用于统计和优化

#### 2.2.2 注册信息表（registrations）
```sql
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) NOT NULL UNIQUE,          -- 邮箱（唯一）
    password VARCHAR(255) NOT NULL,             -- 密码
    uid VARCHAR(50),                            -- 用户ID
    "key" VARCHAR(255),                          -- 密钥（key是SQLite关键字，需要引号）
    register_time DATETIME,                      -- 注册时间
    expire_date DATETIME,                        -- 过期日期
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 更新时间
    is_active INTEGER DEFAULT 1                 -- 是否激活（1=激活，0=禁用）
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_registrations_email ON registrations(email);
CREATE INDEX IF NOT EXISTS ix_registrations_id ON registrations(id);
CREATE INDEX IF NOT EXISTS ix_registrations_active ON registrations(is_active);
```

**字段说明：**
- `id`: 自增主键
- `email`: 邮箱地址，唯一索引
- `password`: 密码（存储明文，与现有JSON保持一致）
- `uid`: 用户ID
- `key`: 2s0密钥
- `register_time`: 注册时间
- `expire_date`: 过期日期
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `is_active`: 是否激活（用于标记失效的key）

#### 2.2.3 注册配置表（registration_config）
```sql
CREATE TABLE IF NOT EXISTS registration_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key VARCHAR(50) UNIQUE NOT NULL,     -- 配置键（如：current_index）
    config_value TEXT,                          -- 配置值（JSON或字符串）
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO registration_config (config_key, config_value) 
VALUES ('current_index', '0');
```

**用途：** 存储 `registration_results.json` 中的 `current_index` 等配置信息

#### 2.2.4 z参数缓存表（z_params_cache）
```sql
CREATE TABLE IF NOT EXISTS z_params_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key VARCHAR(50) UNIQUE NOT NULL,      -- 参数键（如：z_param）
    param_value TEXT NOT NULL,                  -- 参数值
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expire_at DATETIME                          -- 过期时间
);

CREATE INDEX IF NOT EXISTS ix_z_params_key ON z_params_cache(param_key);
CREATE INDEX IF NOT EXISTS ix_z_params_expire ON z_params_cache(expire_at);
```

**用途：** 替代 `z_params.json`，存储z参数缓存

### 2.3 缓存策略设计

#### 2.3.1 搜索缓存策略

**缓存键生成：**
```python
cache_key = keyword.lower().strip()  # 统一小写，去除空格
```

**缓存命中逻辑：**
1. 检查缓存是否存在
2. 检查缓存是否过期（基于 `updated_at` 和配置的 `cache_time`）
3. 如果未过期，直接返回缓存结果
4. 如果过期或不存在，执行搜索并更新缓存

**缓存过期策略：**
- 使用配置文件中的 `cache_time`（默认7200秒=2小时）
- 超过过期时间的缓存自动失效，重新搜索

**缓存更新策略：**
- 每次搜索成功后更新 `updated_at` 和 `hit_count`
- **搜索结果为空时不缓存**（避免缓存无效数据）

**增量更新策略（重要）：**
- **场景**：缓存中有10集的解析结果，但实际已更新到15集
- **处理逻辑**：
  1. 比较缓存的 `vod_play_url` 和新搜索的 `vod_play_url`
  2. 识别新增的集数（通过URL数量或URL本身比较）
  3. **只解析新增的集数**（第11-15集），避免重复解析已有集数
  4. 将新增的解析结果合并到缓存中
  5. 更新缓存时间戳
- **优势**：大幅减少解析时间，只解析新增部分
- **示例**：
  - 缓存：10集（已解析）
  - 新搜索：15集（新增5集）
  - 操作：只解析新增的5集，合并到缓存，总耗时从60秒降低到15秒

#### 2.3.2 缓存清理策略

**自动清理：**
- 定期清理过期缓存（可选，通过定时任务）
- 清理超过一定时间未使用的缓存（如30天）

**手动清理：**
- 提供API接口清理指定关键词的缓存
- 提供API接口清理所有过期缓存

### 2.4 数据迁移方案

#### 2.4.1 registration_results.json 迁移

**迁移步骤：**
1. 读取 `data/registration_results.json`
2. 提取 `current_index` 存储到 `registration_config` 表
3. 遍历 `keys` 数组，插入到 `registrations` 表
4. 验证数据完整性
5. 备份原JSON文件（重命名为 `.json.bak`）

**迁移时机：**
- **应用启动时自动检测并迁移**（如果JSON文件存在）
- **如果数据已存在，自动更新**（增量更新，不覆盖已有数据）
- 迁移前自动备份JSON文件

#### 2.4.2 z_params.json 迁移

**迁移步骤：**
1. 读取 `data/z_params.json`
2. 将每个键值对插入到 `z_params_cache` 表
3. 备份原JSON文件

### 2.5 Docker数据持久化方案

#### 2.5.1 Volume挂载策略

**当前配置：**
```yaml
volumes:
  - ./data:/app/data  # 挂载data目录
```

**优化方案：**
- ✅ 保持现有配置（数据目录已挂载）
- ✅ 数据库文件存储在 `data/video_parser.db`
- ✅ 项目更新时，数据库文件随volume保留

#### 2.5.2 数据备份策略

**备份方案：**
1. **自动备份**：定期备份数据库文件（可选）
2. **手动备份**：提供备份脚本
3. **备份位置**：`data/backups/` 目录

**备份命令示例：**
```bash
# 备份数据库
cp data/video_parser.db data/backups/video_parser_$(date +%Y%m%d_%H%M%S).db
```

## 三、代码实现方案

### 3.1 项目结构

```
video-parser-service/
├── api_server.py
├── parsers/
│   ├── search_parser.py          # 需要修改：集成缓存
│   └── paid_key_parser.py        # 需要修改：使用数据库
├── utils/
│   ├── database.py               # 新建：数据库工具类
│   ├── db_migration.py           # 新建：数据迁移工具
│   ├── search_cache.py           # 新建：搜索缓存管理
│   └── z_param_manager.py        # 需要修改：使用数据库
└── data/
    ├── video_parser.db            # SQLite数据库文件
    ├── registration_results.json # 迁移后保留备份
    └── z_params.json             # 迁移后保留备份
```

### 3.2 核心模块设计

#### 3.2.1 数据库工具类（utils/database.py）

**功能：**
- 数据库连接管理
- 表结构初始化
- 通用CRUD操作
- 连接池管理（可选）

**主要方法：**
```python
class Database:
    def __init__(self, db_path: str)
    def init_tables(self)  # 初始化所有表
    def get_connection(self)  # 获取数据库连接
    def execute_query(self, query: str, params: tuple)  # 执行查询
    def execute_update(self, query: str, params: tuple)  # 执行更新
    def close(self)  # 关闭连接
```

#### 3.2.2 搜索缓存管理（utils/search_cache.py）

**功能：**
- 搜索缓存读写
- 缓存过期检查
- 缓存清理
- **增量更新**：识别并只解析新增集数

**主要方法：**
```python
class SearchCache:
    def __init__(self, db: Database, cache_time: int = 7200)
    def get_cache(self, keyword: str) -> Optional[Dict]  # 获取缓存
    def set_cache(self, keyword: str, results: Dict)  # 设置缓存
    def is_expired(self, keyword: str) -> bool  # 检查是否过期
    def clear_cache(self, keyword: str)  # 清除指定缓存
    def clear_expired_cache(self)  # 清除过期缓存
    def get_cache_stats(self) -> Dict  # 获取缓存统计
    def compare_and_get_new_episodes(self, cached_item: Dict, new_item: Dict) -> Dict  # 比较并获取新增集数
    def merge_results(self, cached_results: Dict, new_results: Dict) -> Dict  # 合并结果
```

#### 3.2.3 数据迁移工具（utils/db_migration.py）

**功能：**
- 从JSON文件迁移数据到数据库
- 数据验证
- 备份原文件

**主要方法：**
```python
class DBMigration:
    def migrate_registration_results(self)  # 迁移registration_results.json
    def migrate_z_params(self)  # 迁移z_params.json
    def verify_migration(self) -> bool  # 验证迁移结果
    def backup_json_files(self)  # 备份JSON文件
```

#### 3.2.4 修改现有模块

**parsers/search_parser.py：**
- 在 `search_and_parse` 方法中集成缓存逻辑
- **缓存命中流程**：
  1. 检查缓存是否存在且未过期
  2. 如果命中，比较缓存结果和新搜索结果
  3. **如果有新增集数**：只解析新增部分，合并到缓存
  4. **如果无新增**：直接返回缓存
- **缓存未命中流程**：
  1. 执行完整搜索和解析流程
  2. 如果结果不为空，保存到缓存

**parsers/paid_key_parser.py：**
- 修改 `load_keys` 方法：从数据库读取
- 修改 `save_keys` 方法：保存到数据库
- 保持API兼容性

**utils/z_param_manager.py：**
- 修改为从数据库读取z参数
- 修改为保存到数据库

### 3.3 API接口设计

#### 3.3.1 缓存管理接口（可选）

```python
# 清除指定关键词的缓存
GET /api/v1/cache/clear?keyword=<关键词>

# 清除所有过期缓存
POST /api/v1/cache/clear-expired

# 获取缓存统计
GET /api/v1/cache/stats
```

## 四、实施计划

### 4.1 开发阶段

#### 阶段1：数据库基础模块（1-2天）
- [ ] 创建 `utils/database.py` - 数据库工具类
- [ ] 实现表结构初始化
- [ ] 实现基础CRUD操作
- [ ] 编写单元测试

#### 阶段2：数据迁移模块（1天）
- [ ] 创建 `utils/db_migration.py` - 数据迁移工具
- [ ] 实现 `registration_results.json` 迁移
- [ ] 实现 `z_params.json` 迁移
- [ ] 实现数据验证和备份
- [ ] 编写迁移测试脚本

#### 阶段3：搜索缓存模块（1-2天）
- [ ] 创建 `utils/search_cache.py` - 搜索缓存管理
- [ ] 实现缓存读写逻辑
- [ ] 实现缓存过期检查
- [ ] 集成到 `search_parser.py`
- [ ] 编写单元测试

#### 阶段4：现有模块改造（2-3天）
- [ ] 修改 `parsers/paid_key_parser.py` - 使用数据库
- [ ] 修改 `utils/z_param_manager.py` - 使用数据库
- [ ] 保持API兼容性
- [ ] 编写集成测试

#### 阶段5：应用启动集成（1天）
- [ ] 在 `api_server.py` 启动时初始化数据库
- [ ] 自动执行数据迁移（如果需要）
- [ ] 添加健康检查（数据库连接状态）

#### 阶段6：测试和优化（2-3天）
- [ ] 本地功能测试
- [ ] Docker部署测试
- [ ] 性能测试（缓存命中率）
- [ ] 数据持久化测试
- [ ] 修复bug和优化

### 4.2 测试计划

#### 4.2.1 单元测试
- 数据库操作测试
- 缓存读写测试
- 数据迁移测试

#### 4.2.2 集成测试
- 搜索缓存流程测试
- 数据迁移流程测试
- API接口测试

#### 4.2.3 本地测试方案

**测试环境准备：**
```bash
# 1. 创建测试数据库
python -m utils.db_migration --init-db

# 2. 迁移现有数据
python -m utils.db_migration --migrate-all

# 3. 启动服务
python api_server.py

# 4. 测试搜索缓存
curl "http://localhost:8000/api/v1/search?ac=videolist&wd=测试关键词"

# 5. 再次请求相同关键词，验证缓存命中
curl "http://localhost:8000/api/v1/search?ac=videolist&wd=测试关键词"

# 6. 检查数据库
sqlite3 data/video_parser.db "SELECT * FROM search_cache;"
```

**测试用例：**
1. **缓存命中测试**
   - 第一次搜索关键词A → 应该执行搜索并缓存
   - 第二次搜索关键词A（无更新） → 应该直接返回缓存（日志显示"缓存命中"）

2. **增量更新测试**
   - 第一次搜索关键词A → 缓存10集
   - 第二次搜索关键词A（已更新到15集） → 应该只解析新增的5集，合并到缓存
   - 验证：缓存中应该有15集的解析结果，且只解析了5集（日志显示"增量更新：新增5集"）

3. **缓存过期测试**
   - 修改缓存记录的 `updated_at` 为过期时间
   - 搜索相同关键词 → 应该重新搜索并更新缓存

3. **数据迁移测试**
   - 备份现有JSON文件
   - 执行迁移脚本
   - 验证数据库数据完整性
   - 验证原JSON文件已备份

4. **Docker部署测试**
   - 构建镜像
   - 启动容器
   - 执行搜索操作
   - 停止容器
   - 重新启动容器
   - 验证数据是否保留

5. **数据持久化测试**
   - 在Docker中创建数据
   - 删除容器
   - 重新创建容器
   - 验证数据是否保留

## 五、技术细节

### 5.1 数据库连接管理

**连接方式：**
- 使用SQLite的线程安全模式（check_same_thread=False）
- 使用连接上下文管理器确保连接正确关闭
- 考虑使用连接池（如果性能需要）

**示例代码：**
```python
import sqlite3
from contextlib import contextmanager

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_tables()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=10.0
        )
        conn.row_factory = sqlite3.Row  # 返回字典格式
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

### 5.2 JSON字段存储

**SQLite JSON支持：**
- SQLite 3.38+ 支持原生JSON类型
- 使用 `json.dumps()` 序列化，`json.loads()` 反序列化
- 使用JSON函数查询（如 `json_extract()`）

**示例：**
```python
# 存储
results_json = json.dumps(results_dict)
cursor.execute("INSERT INTO search_cache (keyword, results) VALUES (?, ?)", 
               (keyword, results_json))

# 读取
cursor.execute("SELECT results FROM search_cache WHERE keyword = ?", (keyword,))
row = cursor.fetchone()
results_dict = json.loads(row['results'])
```

### 5.3 缓存键规范化

**规范化规则：**
- 统一转换为小写
- 去除首尾空格
- 统一编码（UTF-8）

**示例：**
```python
def normalize_keyword(keyword: str) -> str:
    """规范化搜索关键词"""
    return keyword.lower().strip()
```

### 5.5 增量更新实现细节

**比较逻辑：**
1. **解析URL结构**：使用 `parse_play_urls()` 方法解析 `vod_play_url`
2. **比较平台和URL数量**：
   - 按平台（bilibili、vqq、iqiyi等）分组比较
   - 比较每个平台的URL数量
3. **识别新增URL**：
   - 如果新搜索的URL数量 > 缓存的URL数量，说明有新增
   - 提取新增的URL（从第N+1集开始，N为缓存中的集数）
4. **处理带集标识符格式**：
   - 如果URL格式为 `正片$1$url1#2$url2#3$url3`
   - 通过集标识符（1, 2, 3...）识别新增集数
   - 如果集标识符是中文（如"第1话"），通过位置索引识别

**增量解析流程：**
```python
def incremental_update(cached_results: Dict, new_search_results: Dict) -> Dict:
    """
    增量更新缓存
    
    1. 遍历新搜索结果中的每个视频资源
    2. 在缓存中查找相同vod_name的资源
    3. 比较vod_play_url，识别新增集数
    4. 只解析新增的URL
    5. 合并到缓存结果中
    """
    # 伪代码示例
    for new_item in new_search_results['list']:
        vod_name = new_item['vod_name']
        cached_item = find_in_cache(cached_results, vod_name)
        
        if cached_item:
            # 比较URL，获取新增部分
            new_episodes = compare_urls(cached_item['vod_play_url'], 
                                       new_item['vod_play_url'])
            if new_episodes:
                # 只解析新增的URL
                parsed_new = parse_only_new_urls(new_episodes)
                # 合并到缓存
                merge_to_cache(cached_item, parsed_new)
        else:
            # 新资源，完整解析
            parse_and_cache(new_item)
```

**注意事项：**
- URL顺序可能不一致，需要通过URL本身比较，而不是位置
- 如果URL本身变化了（如第1集URL更新），需要重新解析
- 合并时保持原始格式（带集标识符的格式需要保留）

### 5.4 错误处理

**数据库错误处理：**
- 连接失败：记录错误日志，降级到JSON文件（如果可能）
- 查询失败：记录错误日志，返回空结果或执行搜索
- 迁移失败：记录错误日志，保留原JSON文件

**缓存错误处理：**
- 缓存读取失败：记录警告日志，执行搜索
- 缓存写入失败：记录警告日志，继续执行搜索（不影响功能）

## 六、依赖管理

### 6.1 新增依赖

**无需新增依赖：**
- Python标准库已包含 `sqlite3` 模块
- `json` 模块已包含在标准库中

### 6.2 可选依赖

**如果需要JSON查询功能：**
- SQLite 3.38+ 已支持，无需额外依赖

## 七、部署方案

### 7.1 Docker部署

**docker-compose.yml 保持不变：**
```yaml
volumes:
  - ./data:/app/data  # 数据库文件在此目录，自动持久化
```

**数据持久化：**
- ✅ 数据库文件存储在挂载的volume中
- ✅ 容器删除重建时，数据不会丢失
- ✅ 项目代码更新时，数据不会丢失

### 7.2 数据备份

**备份脚本（可选）：**
```bash
#!/bin/bash
# backup_db.sh
BACKUP_DIR="data/backups"
mkdir -p $BACKUP_DIR
cp data/video_parser.db "$BACKUP_DIR/video_parser_$(date +%Y%m%d_%H%M%S).db"
# 保留最近7天的备份
find $BACKUP_DIR -name "video_parser_*.db" -mtime +7 -delete
```

## 八、风险评估与应对

### 8.1 风险点

1. **数据迁移风险**
   - 风险：迁移过程中数据丢失或损坏
   - 应对：迁移前自动备份JSON文件，迁移后验证数据完整性

2. **数据库文件损坏**
   - 风险：SQLite文件损坏导致服务不可用
   - 应对：定期备份，提供数据恢复机制

3. **性能问题**
   - 风险：数据库操作影响搜索性能
   - 应对：使用索引优化查询，异步写入缓存（可选）

4. **兼容性问题**
   - 风险：现有代码依赖JSON文件
   - 应对：保持API兼容性，逐步迁移

### 8.2 回滚方案

**如果出现问题，可以回滚：**
1. 停止使用数据库，恢复使用JSON文件
2. 从备份恢复JSON文件
3. 修改代码，移除数据库相关逻辑

## 九、验收标准

### 9.1 功能验收

- [ ] 搜索相同关键词时，第二次请求直接返回缓存（日志显示"缓存命中"）
- [ ] **增量更新功能**：当有新集数时，只解析新增部分，合并到缓存（日志显示"增量更新：新增N集"）
- [ ] 缓存过期后，自动重新搜索并更新缓存
- [ ] `registration_results.json` 数据成功迁移到数据库
- [ ] `z_params.json` 数据成功迁移到数据库
- [ ] 现有功能（搜索、解析）正常工作
- [ ] Docker部署后数据持久化正常

### 9.2 性能验收

- [ ] 缓存命中时，响应时间 < 100ms
- [ ] 数据库操作不影响搜索性能
- [ ] 缓存命中率 > 50%（基于实际使用情况）

### 9.3 稳定性验收

- [ ] 数据库文件损坏时，服务能正常降级
- [ ] 数据迁移失败时，不影响现有功能
- [ ] Docker容器重启后，数据不丢失

## 十、后续优化方向

### 10.1 短期优化（可选）

1. **缓存预热**：启动时预加载热门关键词
2. **缓存统计**：提供缓存命中率统计API
3. **自动清理**：定时清理过期缓存

### 10.2 长期优化（可选）

1. **缓存分层**：内存缓存 + 数据库缓存
2. **分布式缓存**：如果需要多实例部署，考虑Redis
3. **数据同步**：多实例之间的数据同步机制

## 十一、开发注意事项

### 11.1 代码规范

- ✅ 不能编造代码，所有代码必须基于现有项目结构
- ✅ 保持API兼容性，不破坏现有功能
- ✅ 添加详细的日志记录
- ✅ 添加错误处理和异常捕获
- ✅ 编写单元测试和集成测试

### 11.2 沟通确认

在开始开发前，需要确认以下细节：

1. **缓存过期时间**
   - 是否使用配置文件中的 `cache_time`？
   - 默认过期时间是多少？

2. **缓存策略**
   - 搜索结果为空时，是否也缓存？
   - 缓存失败时，是否影响搜索功能？

3. **数据迁移时机**
   - 是否在应用启动时自动迁移？
   - 是否需要手动迁移命令？

4. **兼容性要求**
   - ✅ **完全迁移到数据库**（不再使用JSON文件）

5. **性能要求**
   - 缓存命中时，响应时间 < 100ms
   - 数据库操作不影响搜索性能

## 十二、数据库选择评估（SQLite vs PostgreSQL）

### 12.1 项目特点分析

**当前项目特点：**
- 单机部署（Docker单容器）
- 数据量：预计搜索缓存数千到数万条，注册信息数百条
- 并发：中等并发（10-100 QPS）
- 读写比例：读多写少（搜索缓存主要是读）
- 部署复杂度：要求简单，无需额外服务

### 12.2 SQLite vs PostgreSQL 对比

| 维度 | SQLite | PostgreSQL |
|------|--------|------------|
| **部署复杂度** | ✅ 零配置，文件数据库 | ❌ 需要独立服务，需要配置 |
| **性能（单机）** | ✅ 优秀（读性能接近PostgreSQL） | ✅ 优秀 |
| **并发写入** | ⚠️ 较弱（适合读多写少） | ✅ 强（支持高并发写入） |
| **数据量支持** | ✅ 支持GB级别（足够） | ✅ 支持TB级别 |
| **事务支持** | ✅ 完整ACID | ✅ 完整ACID |
| **JSON支持** | ✅ 3.38+原生支持 | ✅ 原生支持 |
| **备份恢复** | ✅ 简单（复制文件） | ⚠️ 需要pg_dump |
| **Docker集成** | ✅ 简单（volume挂载） | ⚠️ 需要单独容器或外部服务 |
| **维护成本** | ✅ 极低 | ⚠️ 需要维护数据库服务 |
| **扩展性** | ⚠️ 单机限制 | ✅ 支持集群、主从复制 |

### 12.3 推荐方案：**SQLite**

**推荐理由：**

1. **符合项目场景**
   - ✅ 单机部署，无需分布式
   - ✅ 数据量适中（搜索缓存预计<10万条）
   - ✅ 读多写少（搜索缓存主要是读操作）
   - ✅ 并发适中（10-100 QPS）

2. **部署优势**
   - ✅ 零配置，无需额外服务
   - ✅ Docker部署简单（volume挂载即可）
   - ✅ 备份简单（复制文件）
   - ✅ 项目更新时数据不丢失（volume持久化）

3. **性能足够**
   - ✅ SQLite读性能优秀（接近PostgreSQL）
   - ✅ 搜索缓存场景主要是读操作
   - ✅ 有索引优化，查询速度<10ms

4. **维护成本低**
   - ✅ 无需维护数据库服务
   - ✅ 无需数据库管理员
   - ✅ 故障排查简单

**何时考虑PostgreSQL：**
- 如果未来需要多实例部署（分布式）
- 如果数据量超过100万条
- 如果需要高并发写入（>1000 QPS）
- 如果需要复杂查询（多表JOIN、聚合分析）

### 12.4 最终建议

**当前阶段：使用SQLite**
- ✅ 完全满足当前需求
- ✅ 部署和维护简单
- ✅ 性能足够
- ✅ 成本低

**未来扩展：**
- 如果项目规模扩大，可以平滑迁移到PostgreSQL
- SQLite和PostgreSQL都支持SQL标准，迁移成本较低

## 十三、总结

本项目规划文档详细描述了：
1. ✅ 数据库集成方案（**SQLite**，推荐）
2. ✅ 搜索缓存机制设计（**缓存完整搜索结果和解析结果**）
3. ✅ 数据迁移方案（**自动迁移和更新**）
4. ✅ Docker数据持久化方案
5. ✅ 本地测试方案
6. ✅ 实施计划和验收标准
7. ✅ 数据库选择评估（SQLite vs PostgreSQL）

**已确认的需求：**
- ✅ 缓存时间：使用配置文件中的 `cache_time`（默认7200秒）
- ✅ 搜索结果为空时不缓存
- ✅ **增量更新**：当有新集数时，只解析新增部分，合并到缓存
- ✅ 数据迁移自动执行，已存在时自动更新
- ✅ 完全迁移到数据库（不再使用JSON文件）
- ✅ 使用SQLite数据库

**下一步行动：**
1. ✅ 技术方案已确认
2. 开始阶段1开发：数据库基础模块
3. 逐步实施各阶段功能
4. 完成测试和验收

---

**文档版本：** v1.0  
**创建日期：** 2025-01-04  
**最后更新：** 2025-01-04
