# MoonTV Search Worker

独立的 Cloudflare Workers 搜索服务，支持流式返回搜索结果（SSE）。

## 部署

1. 安装依赖：

```bash
npm install
```

2. 配置 Wrangler（如果还没有登录）：

```bash
npx wrangler login
```

3. 部署到 Cloudflare：

```bash
npx wrangler deploy
```

部署成功后，你会得到一个 Worker URL，例如：

```
https://moontv-search-worker.your-subdomain.workers.dev
```

## 配置前端使用 Worker

在项目根目录的 `.env.local` 文件中添加：

```env
NEXT_PUBLIC_CF_SEARCH_WORKER_URL=https://moontv-search-worker.your-subdomain.workers.dev
```

**注意**：请将上面的 URL 替换为你实际部署的 Worker URL。

## 功能特性

- ✅ 流式返回搜索结果（Server-Sent Events）
- ✅ 多源并发搜索
- ✅ 自动去重
- ✅ 敏感内容过滤
- ✅ CORS 支持
- ✅ 超时控制

## API 使用

### 搜索接口

```
GET /?q={query}
```

**参数：**

- `q`: 搜索关键词（必需）

**响应格式（SSE）：**

```
data: {"results": [...], "done": false, "timestamp": 1234567890}

data: {"results": [], "done": true, "timestamp": 1234567890}
```

**示例：**

```bash
curl "https://moontv-search-worker.your-subdomain.workers.dev/?q=电影"
```

## 本地开发

```bash
npm run dev
```

## 更新源配置

如需更新搜索源配置，编辑 `index.ts` 中的 `SOURCE_CONFIG` 数组，然后重新部署：

```bash
npx wrangler deploy
```
