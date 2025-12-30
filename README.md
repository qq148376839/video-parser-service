# 视频解析服务 - Docker部署版

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

### 解析接口
```
GET /api/v1/parse?url=<视频URL>&parser_url=<解析网站URL>
```

### 搜索接口
```
GET /api/v1/search?ac=videolist&wd=<关键词>&page=<页码>
```

## 配置说明

配置文件：`data/config.json`

- `cache_time`: 缓存时间（秒）

## 数据目录

- `data/config.json`: 配置文件
- `data/z_params.json`: z参数缓存（自动生成）
- `data/logs/`: 日志文件

## 故障排查

1. 查看日志：`docker-compose logs -f`
2. 检查健康状态：`curl http://localhost:1233/health`
3. 查看z参数状态：检查日志中的z参数相关信息
