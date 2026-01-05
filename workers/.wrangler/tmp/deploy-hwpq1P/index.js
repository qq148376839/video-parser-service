var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// index.ts
var SOURCE_CONFIG = [
  {
    key: "jinchancaiji",
    api: "https://zy.jinchancaiji.com/api.php/provide/vod",
    name: "\u91D1\u8749\u91C7\u96C6",
    detail: "http://caiji.dyttzyapi.com"
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
  jinchancaiji: 1
  // 暴风资源 - 通常较快
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
        const playUrlRegex = /\$(https?:\/\/[^"'\s$]+)/g;
        const vod_play_url_array = item.vod_play_url.split("$$$");
        vod_play_url_array.forEach((url) => {
          const matches = url.match(playUrlRegex) || [];
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
var worker = {
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
var index_default = worker;
export {
  index_default as default
};
//# sourceMappingURL=index.js.map
