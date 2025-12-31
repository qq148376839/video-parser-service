"""
M3U8清理工具模块
用于清理m3u8文件中的多余数据（如cachem3u8.2s0.cn的URL）
"""
import re
from typing import List
from urllib.parse import urlparse
from collections import Counter
from utils.logger import logger


class M3U8Cleaner:
    """M3U8文件清理器"""
    
    # 需要清理的域名模式
    CLEAN_PATTERNS = [
        r'cachem3u8\.2s0\.cn',  # 2s0缓存域名
        # 可以添加更多需要清理的域名模式
    ]
    
    @staticmethod
    def clean_m3u8_content(content: str) -> str:
        """
        清理m3u8文件内容，通过统计域名频率移除少数派域名（通常是广告或注入）
        
        确保删除URL时同时删除对应的#EXTINF标签，避免产生孤立的标签
        
        Args:
            content: m3u8文件内容
        
        Returns:
            清理后的m3u8文件内容
        """
        lines = content.split('\n')
        
        # 1. 统计所有绝对路径URL的域名
        urls = [line.strip() for line in lines if line.strip().startswith(('http://', 'https://'))]
        absolute_domains = [urlparse(url).netloc for url in urls]
        
        # 如果没有绝对路径URL，直接返回原始内容（或者是纯相对路径，无需清理）
        if not absolute_domains:
            return content
            
        domain_counts = Counter(absolute_domains)
        
        # 找到出现次数最多的域名（可能有多个并列第一）
        # 这里的逻辑是：保留多数派域名，清理少数派域名
        max_count = domain_counts.most_common(1)[0][1]
        majority_domains = {d for d, c in domain_counts.items() if c == max_count}
        
        cleaned_lines = []
        removed_count = 0
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            should_remove = False
            
            # 检查是否是绝对路径URL
            if line_stripped.startswith(('http://', 'https://')):
                current_domain = urlparse(line_stripped).netloc
                
                # 如果当前域名不在多数派域名中，说明是少数派（注入/广告），需要清理
                if current_domain not in majority_domains:
                    should_remove = True
            
            # 兼容旧的模式匹配逻辑（可选，如果用户还想保留特定的黑名单）
            # 如果尚未决定删除，再检查黑名单
            if not should_remove:
                for pattern in M3U8Cleaner.CLEAN_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        should_remove = True
                        break

            if should_remove:
                # 检查前一行是否是#EXTINF标签，如果是也删除
                if cleaned_lines and cleaned_lines[-1].strip().startswith('#EXTINF'):
                    cleaned_lines.pop()
                    # logger.debug(f"删除孤立的#EXTINF标签")
                
                removed_count += 1
                continue
            
            cleaned_lines.append(line)
        
        # 后处理：清理可能存在的孤立#EXTINF标签（双重保险）
        final_lines = []
        i = 0
        while i < len(cleaned_lines):
            line = cleaned_lines[i]
            line_stripped = line.strip()
            
            # 如果是#EXTINF标签，检查下一行
            if line_stripped.startswith('#EXTINF'):
                if i + 1 < len(cleaned_lines):
                    next_line = cleaned_lines[i + 1].strip()
                    # 如果下一行是URL（绝对或相对），保留这两行
                    # 判断逻辑：是http开头，或者不以#开头且非空（相对路径）
                    is_url = next_line.startswith(('http://', 'https://')) or (next_line and not next_line.startswith('#'))
                    
                    if is_url:
                        final_lines.append(line)
                        final_lines.append(cleaned_lines[i + 1])
                        i += 2
                        continue
                    # 如果下一行也是#EXTINF标签，说明前一个#EXTINF是孤立的
                    elif next_line.startswith('#EXTINF'):
                        logger.warning(f"发现并删除孤立的#EXTINF标签（行 {i+1}，下一行也是#EXTINF）")
                        i += 1
                        continue
                    # 如果下一行是空行或注释，可能是格式问题，也删除
                    elif not next_line or next_line.startswith('#'):
                        # logger.warning(f"发现并删除孤立的#EXTINF标签（行 {i+1}，下一行不是URL）")
                        i += 1
                        continue
                    else:
                        final_lines.append(line)
                        i += 1
                        continue
                else:
                    # 文件末尾的孤立#EXTINF标签
                    # logger.warning(f"发现并删除文件末尾的孤立#EXTINF标签（行 {i+1}）")
                    i += 1
                    continue
            
            # 其他行正常添加
            final_lines.append(line)
            i += 1
        
        cleaned_content = '\n'.join(final_lines)
        
        if removed_count > 0:
            logger.info(f"M3U8清理: 移除了 {removed_count} 行内容（基于域名频率或黑名单）")
        
        return cleaned_content
    
    @staticmethod
    def clean_m3u8_file(file_path: str) -> bool:
        """
        清理m3u8文件
        
        Args:
            file_path: m3u8文件路径
        
        Returns:
            是否清理成功
        """
        try:
            # 读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 清理内容
            cleaned_content = M3U8Cleaner.clean_m3u8_content(content)
            
            # 写回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)
            
            logger.debug(f"M3U8文件清理成功: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"M3U8文件清理失败: {e}")
            return False
