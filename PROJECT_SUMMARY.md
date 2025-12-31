# 视频解析服务项目总结

## 项目概述

视频解析服务是一个基于 FastAPI 的 RESTful API 服务，用于搜索和解析视频资源，支持多个视频平台（爱奇艺、腾讯视频、优酷、B站等）。

## 核心功能

### 1. 视频搜索
- 支持多站点并发搜索
- 自动合并和去重搜索结果
- 优化搜索性能（超时5秒，并发10个）

### 2. 视频解析
支持三种解析方案（按优先级）：

1. **2s0解析器**（第一优先级）
   - 使用付费key获取m3u8 URL
   - 支持多key轮询和过期管理
   - 失败重试机制（最多2次）
   - 自动下载和清理m3u8文件

2. **z参数解析器**（第二优先级）
   - 使用z参数调用API
   - 支持HTTP和Playwright两种方式更新参数

3. **解密解析器**（第三优先级）
   - 使用解密方案解析
   - 支持iframe页面解析

### 3. M3U8文件管理
- 自动下载和缓存m3u8文件
- 清理包含特定域名的URL（如cachem3u8.2s0.cn）
- 避免重复下载相同hash的文件
- 提供本地API接口访问m3u8文件

### 4. 多集支持
- 支持带集标识符的多集格式：`[集数或集名]$[URL]#[集数或集名]$[URL]#...`
- 保留集标识符，只替换URL部分
- 并发解析多集，保持顺序

## 项目结构

```
video-parser-service/
├── api_server.py              # FastAPI主服务
├── parsers/                   # 解析器模块
│   ├── paid_key_parser.py     # 2s0解析器
│   ├── z_param_parser.py      # z参数解析器
│   ├── decrypt_parser.py      # 解密解析器
│   └── search_parser.py       # 搜索解析器
├── utils/                     # 工具模块
│   ├── logger.py              # 日志工具
│   ├── config_loader.py       # 配置加载器
│   ├── m3u8_cleaner.py        # M3U8清理工具
│   ├── z_param_manager.py     # z参数管理器
│   └── file_lock.py           # 文件锁工具
├── data/                      # 数据目录
│   ├── config.json            # 配置文件
│   ├── registration_results.json  # 2s0 key注册结果
│   ├── z_params.json          # z参数缓存
│   └── m3u8_cache/            # M3U8文件缓存
├── requirements.txt           # 依赖列表
├── Dockerfile                 # Docker镜像配置
├── docker-compose.yml         # Docker Compose配置
└── README.md                  # 项目说明文档
```

## API接口

### 1. 搜索接口
```
GET /api/v1/search?ac=videolist&wd=<关键词>&page=<页码>
```

**功能：** 搜索视频资源并自动解析为m3u8地址

**响应格式：**
```json
{
  "code": 1,
  "msg": "数据列表",
  "page": 1,
  "pagecount": 1,
  "limit": 20,
  "total": 1,
  "list": [
    {
      "vod_name": "视频名称",
      "vod_play_url": "正片$http://localhost:8000/api/v1/m3u8/xxx"
    }
  ]
}
```

### 2. 解析接口
```
GET /api/v1/parse?url=<视频URL>&parser_url=<解析网站URL>
```

**功能：** 解析单个视频URL为m3u8地址

### 3. M3U8文件接口
```
GET /api/v1/m3u8/<file_id>
```

**功能：** 获取缓存的m3u8文件内容

### 4. 健康检查接口
```
GET /health
```

## 性能优化

### 搜索性能优化
- ✅ 超时时间：从10秒减少到5秒（连接3秒，读取5秒）
- ✅ 并发数：从5个增加到10个
- ✅ 快速失败：添加超时异常处理

### 解析性能优化
- ✅ M3U8文件缓存：避免重复下载相同hash的文件
- ✅ 并发解析：多集视频使用线程池并发解析
- ✅ URL去重：自动去除重复的解析结果

## 容错机制

### 解析器重试机制
- ✅ 2s0解析器：失败时自动重试2次
- ✅ 自动切换：重试失败后自动切换到下一个解析器
- ✅ 日志记录：详细记录重试和切换过程

### 错误处理
- ✅ 网络超时处理
- ✅ JSON解析错误处理
- ✅ 文件操作异常处理
- ✅ 优雅降级：解析失败时返回空结果而非崩溃

## 数据格式

### 多集URL格式
支持两种格式：

1. **标准格式：**
   ```
   正片$url1$url2$url3
   ```

2. **带集标识符格式：**
   ```
   正片$1$url1#2$url2#3$url3
   正片$第1话$url1#第2话$url2
   ```

### M3U8文件格式
- 自动清理包含 `cachem3u8.2s0.cn` 的URL
- 确保格式正确，避免孤立的 `#EXTINF` 标签
- 支持 `#EXT-X-DISCONTINUITY` 和 `#EXT-X-KEY` 标签

## 配置说明

### config.json
```json
{
  "cache_time": 3600,
  "api_sites": [
    {
      "name": "站点名称",
      "api": "https://api.example.com"
    }
  ]
}
```

### registration_results.json
```json
{
  "current_index": 0,
  "keys": [
    {
      "uid": "用户ID",
      "key": "密钥",
      "email": "邮箱",
      "register_time": "注册时间",
      "expire_date": "过期时间"
    }
  ]
}
```

## 部署说明

### Docker部署
```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 环境变量
- `API_BASE_URL`: API服务的基础URL（默认：http://localhost:8000）
- `PORT`: 服务端口（默认：8000）

## 日志说明

日志文件位置：`data/logs/api_server.log`

日志级别：
- INFO: 正常操作日志
- WARNING: 警告信息（如解析失败、重试等）
- ERROR: 错误信息
- DEBUG: 调试信息

## 更新日志

### 2025-12-31
- ✅ 优化搜索性能（超时5秒，并发10个）
- ✅ 添加2s0解析器重试机制（最多2次）
- ✅ 修复M3U8清理脚本，避免孤立标签
- ✅ 支持带集标识符的多集URL格式
- ✅ 添加M3U8文件缓存检查，避免重复下载
- ✅ URL去重，避免重复的解析结果

## 注意事项

1. **2s0 Key管理**
   - 需要定期注册新的key
   - 过期key会自动删除
   - 支持多key轮询

2. **z参数管理**
   - 自动检测过期并更新
   - 优先使用HTTP方式，失败时使用Playwright

3. **M3U8缓存**
   - 缓存文件存储在 `data/m3u8_cache/`
   - 相同hash的文件只下载一次
   - 建议定期清理旧缓存文件

4. **性能建议**
   - 搜索接口：建议使用较短的超时时间
   - 解析接口：多集视频会并发解析，注意线程数限制
   - 缓存管理：定期清理旧的m3u8文件
