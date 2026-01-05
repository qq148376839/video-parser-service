/**
 * MoonTV Cloudflare Workers Search API
 * 独立的搜索 Worker，支持流式返回结果 (SSE)
 */

// 源配置（直接硬编码，避免依赖文件系统）
const SOURCE_CONFIG = [
  {
    key: "jinchancaiji",
    api: "https://zy.jinchancaiji.com/api.php/provide/vod",
    name: "金蝉采集",
    detail: "http://caiji.dyttzyapi.com"
  },
  {
    key: "789caiji",
    api: "https://gfjx.riowang.win/api/v1/search",
    name: "789采集"
  }
];

// 敏感词配置（用于过滤）
const YELLOW_WORDS = [
  '伦理',
  '三级',
  '金瓶梅',
  '色戒',
  '肉蒲团',
  '艳史',
  '淫',
  '激情',
  '乱伦',
  '性爱',
  '自慰',
  'AV',
  'H片',
  'R级',
  '成人',
  '限制级',
];

// 源优先级配置
const SOURCE_PRIORITY = {
  jinchancaiji: 1, // 暴风资源 - 通常较快
};

// API配置
const API_CONFIG = {
  search: {
    path: '?ac=videolist&wd=',
    headers: {
      'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
      Accept: 'application/json',
    },
  },
};

// 辅助函数：清理HTML标签
function cleanHtmlTags(str) {
  if (!str) return '';
  return str.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim();
}

/**
 * 执行搜索请求
 */
async function searchFromApi(apiSite, query) {
  try {
    const apiBaseUrl = apiSite.api;
    const apiUrl = apiBaseUrl + API_CONFIG.search.path + encodeURIComponent(query);
    
    // 超时控制
    const controller = new AbortController();
    const timeoutMs = 3000; // 默认3秒超时
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const response = await fetch(apiUrl, {
      headers: API_CONFIG.search.headers,
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);

    if (!response.ok) return [];

    const data = await response.json();
    
    if (!data || !data.list || !Array.isArray(data.list) || data.list.length === 0) {
      return [];
    }

    // 处理结果
    return data.list.map((item) => {
      let episodes = [];

      if (item.vod_play_url) {
        // 使用正则表达式从 vod_play_url 提取所有播放链接（不限制格式）
        const playUrlRegex = /\$(https?:\/\/[^"'\s$]+)/g;
        // 先用 $$$ 分割
        const vod_play_url_array = item.vod_play_url.split('$$$');
        // 对每个分片做匹配，取匹配到最多的作为结果
        vod_play_url_array.forEach((url) => {
          const matches = url.match(playUrlRegex) || [];
          if (matches.length > episodes.length) {
            episodes = matches;
          }
        });

        episodes = Array.from(new Set(episodes)).map((link) => {
          link = link.substring(1); // 去掉开头的 $
          const parenIndex = link.indexOf('(');
          return parenIndex > 0 ? link.substring(0, parenIndex) : link;
        });
      }

      return {
        id: item.vod_id.toString(),
        title: item.vod_name.trim().replace(/\s+/g, ' '),
        poster: item.vod_pic,
        episodes,
        source: apiSite.key,
        source_name: apiSite.name,
        class: item.vod_class,
        year: item.vod_year ? item.vod_year.match(/\d{4}/)?.[0] || '' : 'unknown',
        desc: cleanHtmlTags(item.vod_content || ''),
        type_name: item.type_name,
        douban_id: item.vod_douban_id,
      };
    });
  } catch (error) {
    // 忽略错误，返回空数组
    return [];
  }
}

/**
 * Cloudflare Worker 主逻辑
 */
const worker = {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const query = url.searchParams.get('q');
    
    // CORS 头部
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // 处理 OPTIONS 请求
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    if (!query) {
      return new Response('Missing query parameter', { 
        status: 400,
        headers: corsHeaders 
      });
    }

    // 1. 设置 SSE 响应流
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    // 2. 构造响应对象（立即返回，不等待搜索完成）
    const response = new Response(readable, {
      headers: {
        ...corsHeaders,
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
      },
    });

    // 3. 异步执行搜索任务
    ctx.waitUntil((async () => {
      try {
        // 过滤禁用的源（此处默认全部启用）
        const apiSites = SOURCE_CONFIG;

        // 按优先级排序源
        const sortedSites = apiSites.sort((a, b) => {
          const priorityA = SOURCE_PRIORITY[a.key] || 999;
          const priorityB = SOURCE_PRIORITY[b.key] || 999;
          return priorityA - priorityB;
        });

        // 已见结果去重
        const seenResults = new Set();
        
        // 并发搜索所有源
        const searchTasks = sortedSites.map(async (site) => {
          try {
            const results = await searchFromApi(site, query);
            
            if (results.length > 0) {
              // 过滤黄色内容
              // 注意：这里简单过滤，如果不需要可以移除
              const filteredResults = results.filter((result) => {
                const typeName = result.type_name || '';
                return !YELLOW_WORDS.some((word) => typeName.includes(word));
              });

              if (filteredResults.length > 0) {
                // 去重
                const newResults = [];
                filteredResults.forEach((result) => {
                  const key = `${result.source}-${result.id}`;
                  if (!seenResults.has(key)) {
                    seenResults.add(key);
                    newResults.push(result);
                  }
                });

                // 推送结果
                if (newResults.length > 0) {
                  const message = JSON.stringify({
                    results: newResults,
                    done: false,
                    timestamp: Date.now()
                  });
                  await writer.write(encoder.encode(`data: ${message}\n\n`));
                }
              }
            }
          } catch (e) {
            // 单个源失败忽略
          }
        });

        // 等待所有源处理完毕
        await Promise.allSettled(searchTasks);
        
        // 发送结束信号
        const doneMessage = JSON.stringify({
          results: [],
          done: true,
          timestamp: Date.now()
        });
        await writer.write(encoder.encode(`data: ${doneMessage}\n\n`));
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('Search worker error:', err);
      } finally {
        await writer.close();
      }
    })());

    return response;
  }
};

export default worker;
