# 视频解析服务

一个基于 FastAPI 的视频解析服务，支持搜索和解析多个视频平台的资源。

## 核心功能

- 🔍 **多站点搜索**：并发搜索多个API站点，自动合并和去重
- 🎬 **多方案解析**：支持2s0、z参数、解密三种解析方案，自动切换
- 📦 **M3U8管理**：自动下载、清理和缓存m3u8文件
- 🎯 **多集支持**：支持带集标识符的多集连续剧格式
- ⚡ **性能优化**：搜索超时5秒，并发10个，快速失败机制
- 🔄 **容错机制**：解析失败自动重试（最多2次），自动切换解析器

## 快速开始

### 1. 配置
编辑 `data/config.json`，配置API站点。

### 2. 构建和启动
```bash
docker-compose build
docker-compose up -d
```

### 3. 验证
```bash
# 查看日志
docker-compose logs -f

# 健康检查
curl http://localhost:1233/health

# API文档
浏览器访问: http://localhost:1233/docs
```

## API接口

### 搜索接口
```
GET /api/v1/search?ac=videolist&wd=<关键词>&page=<页码>
```
搜索视频资源并自动解析为m3u8地址。

### 解析接口
```
GET /api/v1/parse?url=<视频URL>&parser_url=<解析网站URL>
```
解析单个视频URL为m3u8地址。

### M3U8文件接口
```
GET /api/v1/m3u8/<file_id>
```
获取缓存的m3u8文件内容。

### 健康检查接口
```
GET /health
```

## 项目结构

```
video-parser-service/
├── api_server.py              # FastAPI主服务
├── parsers/                   # 解析器模块
│   ├── paid_key_parser.py     # 2s0解析器（第一优先级）
│   ├── z_param_parser.py      # z参数解析器（第二优先级）
│   ├── decrypt_parser.py      # 解密解析器（第三优先级）
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
存储2s0解析器的key信息，格式：
```json
{
  "current_index": 0,
  "keys": [
    {
      "uid": "用户ID",
      "key": "密钥",
      "email": "邮箱",
      "register_time": "2025-01-01 00:00:00",
      "expire_date": "2025-12-31 00:00:00"
    }
  ]
}
```

## 性能优化

- ✅ 搜索超时：5秒（连接3秒，读取5秒）
- ✅ 并发数：最多10个站点并发搜索
- ✅ M3U8缓存：避免重复下载相同hash的文件
- ✅ URL去重：自动去除重复的解析结果

## 容错机制

- ✅ 2s0解析器：失败时自动重试2次
- ✅ 自动切换：重试失败后自动切换到下一个解析器
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

## 故障排查

1. 查看日志：`docker-compose logs -f`
2. 检查健康状态：`curl http://localhost:1233/health`
3. 查看z参数状态：检查日志中的z参数相关信息
4. 检查2s0 key：查看 `data/registration_results.json` 中的key状态

## 详细文档

更多详细信息请参考：
- `PROJECT_SUMMARY.md` - 项目总结文档
- `PRODUCT_DESIGN.md` - 产品设计文档

## 更新日志

### 2025-12-31
- ✅ 优化搜索性能（超时5秒，并发10个）
- ✅ 添加2s0解析器重试机制（最多2次）
- ✅ 修复M3U8清理脚本，避免孤立标签
- ✅ 支持带集标识符的多集URL格式
- ✅ 添加M3U8文件缓存检查，避免重复下载
- ✅ URL去重，避免重复的解析结果
