var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// index.ts
var SOURCE_CONFIG = [
  {
    key: "dyttzy",
    api: "http://caiji.dyttzyapi.com/api.php/provide/vod",
    name: "\u7535\u5F71\u5929\u5802\u8D44\u6E90",
    detail: "http://caiji.dyttzyapi.com"
  },
  {
    key: "heimuer",
    api: "https://json.heimuer.xyz/api.php/provide/vod",
    name: "\u9ED1\u6728\u8033",
    detail: "https://heimuer.tv"
  },
  {
    key: "ruyi",
    api: "http://cj.rycjapi.com/api.php/provide/vod",
    name: "\u5982\u610F\u8D44\u6E90"
  },
  {
    key: "bfzy",
    api: "https://bfzyapi.com/api.php/provide/vod",
    name: "\u66B4\u98CE\u8D44\u6E90"
  },
  {
    key: "tyyszy",
    api: "https://tyyszy.com/api.php/provide/vod",
    name: "\u5929\u6DAF\u8D44\u6E90"
  },
  {
    key: "ffzy",
    api: "http://ffzy5.tv/api.php/provide/vod",
    name: "\u975E\u51E1\u5F71\u89C6",
    detail: "http://ffzy5.tv"
  },
  {
    key: "zy360",
    api: "https://360zy.com/api.php/provide/vod",
    name: "360\u8D44\u6E90"
  },
  {
    key: "maotaizy",
    api: "https://caiji.maotaizy.cc/api.php/provide/vod",
    name: "\u8305\u53F0\u8D44\u6E90"
  },
  {
    key: "wolong",
    api: "https://wolongzyw.com/api.php/provide/vod",
    name: "\u5367\u9F99\u8D44\u6E90"
  },
  {
    key: "jisu",
    api: "https://jszyapi.com/api.php/provide/vod",
    name: "\u6781\u901F\u8D44\u6E90",
    detail: "https://jszyapi.com"
  },
  {
    key: "dbzy",
    api: "https://dbzy.tv/api.php/provide/vod",
    name: "\u8C46\u74E3\u8D44\u6E90"
  },
  {
    key: "mozhua",
    api: "https://mozhuazy.com/api.php/provide/vod",
    name: "\u9B54\u722A\u8D44\u6E90"
  },
  {
    key: "mdzy",
    api: "https://www.mdzyapi.com/api.php/provide/vod",
    name: "\u9B54\u90FD\u8D44\u6E90"
  },
  {
    key: "zuid",
    api: "https://api.zuidapi.com/api.php/provide/vod",
    name: "\u6700\u5927\u8D44\u6E90"
  },
  {
    key: "yinghua",
    api: "https://m3u8.apiyhzy.com/api.php/provide/vod",
    name: "\u6A31\u82B1\u8D44\u6E90"
  },
  {
    key: "wujin",
    api: "https://api.wujinapi.me/api.php/provide/vod",
    name: "\u65E0\u5C3D\u8D44\u6E90"
  },
  {
    key: "wwzy",
    api: "https://wwzy.tv/api.php/provide/vod",
    name: "\u65FA\u65FA\u77ED\u5267"
  },
  {
    key: "ikun",
    api: "https://ikunzyapi.com/api.php/provide/vod",
    name: "iKun\u8D44\u6E90"
  },
  {
    key: "lzi",
    api: "https://cj.lziapi.com/api.php/provide/vod",
    name: "\u91CF\u5B50\u8D44\u6E90\u7AD9"
  },
  {
    key: "xiaomaomi",
    api: "https://zy.xmm.hk/api.php/provide/vod",
    name: "\u5C0F\u732B\u54AA\u8D44\u6E90"
  },
  {
    key: "gay",
    api: "https://cfapi.riowang.win/api/another",
    name: "gay\u8D44\u6E90"
  },
  {
    key: "hongniu",
    api: "https://www.hongniuzy2.com/api.php/provide/vod",
    name: "\u7EA2\u725B\u8D44\u6E90"
  },
  {
    key: "sdzy",
    api: "https://xsd.sdzyapi.com/api.php/provide/vod",
    name: "\u95EA\u7535\u8D44\u6E90"
  },
  {
    key: "xinlang",
    api: "https://api.xinlangapi.com/xinlangapi.php/provide/vod",
    name: "\u65B0\u6D6A\u8D44\u6E90"
  },
  {
    key: "yzzy",
    api: "https://api.yzzy-api.com/inc/apijson.php/provide/vod",
    name: "\u4E91\u8D44\u6E90"
  },
  {
    key: "suboc",
    api: "https://subocj.com/api.php/provide/vod",
    name: "\u901F\u64AD\u8D44\u6E90"
  },
  {
    key: "hhzy",
    api: "https://hhzyapi.com/api.php/provide/vod",
    name: "\u6D77\u6D77\u8D44\u6E90"
  },
  {
    key: "dbzy5",
    api: "https://caiji.dbzy5.com/api.php/provide/vod",
    name: "\u8C46\u74E3\u8D44\u6E905"
  },
  {
    key: "okzyw",
    api: "https://api.okzyw.net/api.php/provide/vod",
    name: "OK\u8D44\u6E90\u7F51"
  },
  {
    key: "yayazy",
    api: "https://cj.yayazy.net/api.php/provide/vod",
    name: "\u4E2B\u4E2B\u8D44\u6E90"
  },
  {
    key: "ckzy",
    api: "https://ckzy.me/api.php/provide/vod",
    name: "\u521B\u5BA2\u8D44\u6E90"
  },
  {
    key: "suoniapi",
    api: "https://suoniapi.com/api.php/provide/vod",
    name: "\u9501\u4F60\u8D44\u6E90"
  },
  {
    key: "niuniuzy",
    api: "https://api.niuniuzy.me/api.php/provide/vod",
    name: "\u725B\u725B\u8D44\u6E90"
  },
  {
    key: "789caiji",
    api: "https://gfjx.riowang.win/api/v1/search",
    name: "789\u91C7\u96C6"
  }
];
var YELLOW_WORDS = [
  "\u4F26\u7406",
  "\u4E09\u7EA7",
  "\u91D1\u74F6\u6885",
  "\u8272\u6212",
  "\u8089\u84B2\u56E2",
  "\u8273\u53F2",
  "\u6DEB",
  "\u6FC0\u60C5",
  "\u4E71\u4F26",
  "\u6027\u7231",
  "\u81EA\u6170",
  "AV",
  "H\u7247",
  "R\u7EA7",
  "\u6210\u4EBA",
  "\u9650\u5236\u7EA7"
];
var SOURCE_PRIORITY = {
  bfzy: 1,
  // 暴风资源 - 通常较快
  tyyszy: 2,
  // 天涯资源 - 稳定
  zy360: 3,
  // 360资源 - 较快
  wolong: 4,
  // 卧龙资源 - 中等
  jisu: 5,
  // 极速资源 - 较快
  dbzy: 6
  // 豆瓣资源 - 中等
};
var API_CONFIG = {
  search: {
    path: "?ac=videolist&wd=",
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
      Accept: "application/json"
    }
  }
};
function cleanHtmlTags(str) {
  if (!str) return "";
  return str.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").trim();
}
__name(cleanHtmlTags, "cleanHtmlTags");
async function searchFromApi(apiSite, query) {
  try {
    const apiBaseUrl = apiSite.api;
    const apiUrl = apiBaseUrl + API_CONFIG.search.path + encodeURIComponent(query);
    const controller = new AbortController();
    const timeoutMs = 3e3;
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const response = await fetch(apiUrl, {
      headers: API_CONFIG.search.headers,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (!response.ok) return [];
    const data = await response.json();
    if (!data || !data.list || !Array.isArray(data.list) || data.list.length === 0) {
      return [];
    }
    return data.list.map((item) => {
      let episodes = [];
      if (item.vod_play_url) {
        const m3u8Regex = /\$(https?:\/\/[^"'\s]+?\.m3u8)/g;
        const vod_play_url_array = item.vod_play_url.split("$$$");
        vod_play_url_array.forEach((url) => {
          const matches = url.match(m3u8Regex) || [];
          if (matches.length > episodes.length) {
            episodes = matches;
          }
        });
        episodes = Array.from(new Set(episodes)).map((link) => {
          link = link.substring(1);
          const parenIndex = link.indexOf("(");
          return parenIndex > 0 ? link.substring(0, parenIndex) : link;
        });
      }
      return {
        id: item.vod_id.toString(),
        title: item.vod_name.trim().replace(/\s+/g, " "),
        poster: item.vod_pic,
        episodes,
        source: apiSite.key,
        source_name: apiSite.name,
        class: item.vod_class,
        year: item.vod_year ? item.vod_year.match(/\d{4}/)?.[0] || "" : "unknown",
        desc: cleanHtmlTags(item.vod_content || ""),
        type_name: item.type_name,
        douban_id: item.vod_douban_id
      };
    });
  } catch (error) {
    return [];
  }
}
__name(searchFromApi, "searchFromApi");
var index_default = {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const query = url.searchParams.get("q");
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }
    if (!query) {
      return new Response("Missing query parameter", {
        status: 400,
        headers: corsHeaders
      });
    }
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();
    const response = new Response(readable, {
      headers: {
        ...corsHeaders,
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive"
      }
    });
    ctx.waitUntil((async () => {
      try {
        const apiSites = SOURCE_CONFIG;
        const sortedSites = apiSites.sort((a, b) => {
          const priorityA = SOURCE_PRIORITY[a.key] || 999;
          const priorityB = SOURCE_PRIORITY[b.key] || 999;
          return priorityA - priorityB;
        });
        const seenResults = /* @__PURE__ */ new Set();
        const searchTasks = sortedSites.map(async (site) => {
          try {
            const results = await searchFromApi(site, query);
            if (results.length > 0) {
              const filteredResults = results.filter((result) => {
                const typeName = result.type_name || "";
                return !YELLOW_WORDS.some((word) => typeName.includes(word));
              });
              if (filteredResults.length > 0) {
                const newResults = [];
                filteredResults.forEach((result) => {
                  const key = `${result.source}-${result.id}`;
                  if (!seenResults.has(key)) {
                    seenResults.add(key);
                    newResults.push(result);
                  }
                });
                if (newResults.length > 0) {
                  const message = JSON.stringify({
                    results: newResults,
                    done: false,
                    timestamp: Date.now()
                  });
                  await writer.write(encoder.encode(`data: ${message}

`));
                }
              }
            }
          } catch (e) {
          }
        });
        await Promise.allSettled(searchTasks);
        const doneMessage = JSON.stringify({
          results: [],
          done: true,
          timestamp: Date.now()
        });
        await writer.write(encoder.encode(`data: ${doneMessage}

`));
      } catch (err) {
        console.error("Search worker error:", err);
      } finally {
        await writer.close();
      }
    })());
    return response;
  }
};
export {
  index_default as default
};
//# sourceMappingURL=index.js.map
