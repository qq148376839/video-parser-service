"""
M3U8清理工具模块
用于清理m3u8文件中的多余数据（如cachem3u8.2s0.cn的URL）
"""
import re
from typing import List
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
        清理m3u8文件内容，移除包含特定域名的行
        
        确保删除URL时同时删除对应的#EXTINF标签，避免产生孤立的标签
        
        Args:
            content: m3u8文件内容
        
        Returns:
            清理后的m3u8文件内容
        """
        lines = content.split('\n')
        cleaned_lines = []
        skip_next = False
        
        for i, line in enumerate(lines):
            # 如果上一行标记了跳过，跳过当前行（通常是URL行）
            if skip_next:
                skip_next = False
                continue
            
            # 检查当前行是否包含需要清理的域名
            should_skip = False
            for pattern in M3U8Cleaner.CLEAN_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    should_skip = True
                    break
            
            if should_skip:
                line_stripped = line.strip()
                
                # 情况1: 如果当前行是URL行（以http开头），需要检查前一行是否是#EXTINF
                # 如果是，也要删除前一行（#EXTINF标签），避免产生孤立的标签
                if line_stripped.startswith('http'):
                    # 检查前一行是否是#EXTINF标签
                    if cleaned_lines and cleaned_lines[-1].strip().startswith('#EXTINF'):
                        # 删除前一行（#EXTINF标签）
                        cleaned_lines.pop()
                        logger.debug(f"删除孤立的#EXTINF标签（对应URL包含清理域名）")
                    # 跳过当前URL行
                    continue
                
                # 情况2: 如果当前行是#EXTINF行且包含清理域名，跳过当前行和下一行（URL行）
                elif line_stripped.startswith('#EXTINF'):
                    skip_next = True
                    continue
                
                # 情况3: 其他包含清理域名的行（如注释等），直接跳过
                continue
            
            # 正常行，添加到清理后的列表
            cleaned_lines.append(line)
        
        # 后处理：清理可能存在的孤立#EXTINF标签（双重保险）
        # 检查是否有#EXTINF标签后面没有URL的情况（只删除明显孤立的标签）
        final_lines = []
        i = 0
        while i < len(cleaned_lines):
            line = cleaned_lines[i]
            line_stripped = line.strip()
            
            # 如果是#EXTINF标签，检查下一行
            if line_stripped.startswith('#EXTINF'):
                if i + 1 < len(cleaned_lines):
                    next_line = cleaned_lines[i + 1].strip()
                    # 如果下一行是URL，保留这两行
                    if next_line.startswith('http'):
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
                        logger.warning(f"发现并删除孤立的#EXTINF标签（行 {i+1}，下一行不是URL）")
                        i += 1
                        continue
                    else:
                        # 其他情况，可能是合法的，保留
                        final_lines.append(line)
                        i += 1
                        continue
                else:
                    # 文件末尾的孤立#EXTINF标签
                    logger.warning(f"发现并删除文件末尾的孤立#EXTINF标签（行 {i+1}）")
                    i += 1
                    continue
            
            # 其他行正常添加
            final_lines.append(line)
            i += 1
        
        cleaned_content = '\n'.join(final_lines)
        
        # 统计清理的行数
        original_line_count = len(lines)
        final_line_count = len(final_lines)
        removed_count = original_line_count - final_line_count
        
        if removed_count > 0:
            logger.info(f"M3U8清理: 移除了 {removed_count} 行包含清理域名的内容")
        
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
