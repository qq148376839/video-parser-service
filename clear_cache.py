#!/usr/bin/env python3
"""
清理缓存脚本
用于清理视频解析服务的各种缓存数据
"""
import os
import shutil
import sqlite3
from pathlib import Path
from typing import List

# 项目根目录
project_root = Path(__file__).parent
data_dir = project_root / "data"
db_path = data_dir / "video_parser.db"
m3u8_cache_dir = data_dir / "m3u8_cache"


def clear_m3u8_cache_files(verbose: bool = False, purge_url_parse_cache: bool = False) -> int:
    """
    清理m3u8缓存目录下的m3u8文件（可被服务端任务/接口直接调用）
    
    Args:
        verbose: 是否打印详细信息（CLI脚本使用True；服务端通常用False）
    
    Returns:
        删除的m3u8文件数量
    """
    removed = 0
    
    if not m3u8_cache_dir.exists():
        if verbose:
            print("✓ m3u8缓存目录不存在，无需清理")
        return 0
    
    files = list(m3u8_cache_dir.glob("*.m3u8"))
    if not files:
        if verbose:
            print("✓ m3u8缓存目录为空，无需清理")
        return 0
    
    for file in files:
        try:
            file.unlink()
            removed += 1
            if verbose:
                print(f"✓ 删除m3u8缓存文件: {file.name}")
        except Exception as e:
            if verbose:
                print(f"✗ 删除失败 {file.name}: {e}")
            # 服务端/定时任务场景：尽量继续清理其他文件
            continue
    
    if verbose:
        print(f"✓ 已清理 {removed} 个m3u8缓存文件")
    
    # 可选：同步清理URL解析缓存中指向不存在文件的记录，避免返回“坏缓存”
    if purge_url_parse_cache:
        try:
            from utils.url_parse_cache import url_parse_cache
            purged = url_parse_cache.purge_missing_m3u8_files()
            if verbose and purged > 0:
                print(f"✓ 已清理 {purged} 条无效URL解析缓存记录")
        except Exception as e:
            if verbose:
                print(f"⚠ 清理无效URL解析缓存失败（忽略）: {e}")

    return removed


def clear_m3u8_cache():
    """清理m3u8文件缓存（保持CLI兼容）"""
    clear_m3u8_cache_files(verbose=True)


def clear_database_cache():
    """清理数据库缓存"""
    if not db_path.exists():
        print("✓ 数据库文件不存在，无需清理")
        return
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 清理搜索缓存
        cursor.execute("DELETE FROM search_cache")
        search_count = cursor.rowcount
        print(f"✓ 已清理 {search_count} 条搜索缓存记录")
        
        # 清理URL解析缓存
        cursor.execute("DELETE FROM url_parse_cache")
        url_count = cursor.rowcount
        print(f"✓ 已清理 {url_count} 条URL解析缓存记录")
        
        # 清理z参数缓存（可选，建议保留）
        # cursor.execute("DELETE FROM z_params_cache")
        # z_param_count = cursor.rowcount
        # print(f"✓ 已清理 {z_param_count} 条z参数缓存记录")
        
        conn.commit()
        conn.close()
        print("✓ 数据库缓存清理完成")
        
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            print(f"⚠ 数据库表不存在，可能还未初始化: {e}")
        else:
            print(f"✗ 清理数据库缓存失败: {e}")
    except Exception as e:
        print(f"✗ 清理数据库缓存失败: {e}")


def clear_z_params_json():
    """清理z参数JSON文件（可选）"""
    z_params_file = data_dir / "z_params.json"
    if z_params_file.exists():
        try:
            # 备份原文件
            backup_file = data_dir / "z_params.json.backup"
            if backup_file.exists():
                backup_file.unlink()
            shutil.copy2(z_params_file, backup_file)
            
            # 清空文件内容（保留空JSON对象）
            with open(z_params_file, 'w', encoding='utf-8') as f:
                f.write('{}')
            print(f"✓ 已清空z_params.json（已备份到z_params.json.backup）")
        except Exception as e:
            print(f"✗ 清理z_params.json失败: {e}")
    else:
        print("✓ z_params.json不存在，无需清理")


def clear_all():
    """清理所有缓存"""
    print("=" * 60)
    print("开始清理缓存...")
    print("=" * 60)
    
    # 清理m3u8文件缓存
    print("\n[1/3] 清理m3u8文件缓存...")
    clear_m3u8_cache()
    
    # 清理数据库缓存
    print("\n[2/3] 清理数据库缓存...")
    clear_database_cache()
    
    # 清理z参数JSON（可选）
    print("\n[3/3] 清理z参数JSON文件...")
    response = input("是否清空z_params.json？(y/N): ").strip().lower()
    if response == 'y':
        clear_z_params_json()
    else:
        print("✓ 跳过清理z_params.json（保留z参数）")
    
    print("\n" + "=" * 60)
    print("缓存清理完成！")
    print("=" * 60)


def show_cache_info():
    """显示缓存信息"""
    print("=" * 60)
    print("缓存信息统计")
    print("=" * 60)
    
    # m3u8缓存
    if m3u8_cache_dir.exists():
        m3u8_files = list(m3u8_cache_dir.glob("*.m3u8"))
        total_size = sum(f.stat().st_size for f in m3u8_files)
        print(f"\nm3u8文件缓存:")
        print(f"  文件数量: {len(m3u8_files)}")
        print(f"  总大小: {total_size / 1024 / 1024:.2f} MB")
        print(f"  目录: {m3u8_cache_dir}")
    else:
        print(f"\nm3u8文件缓存: 目录不存在")
    
    # 数据库缓存
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # 搜索缓存
            cursor.execute("SELECT COUNT(*) FROM search_cache")
            search_count = cursor.fetchone()[0]
            
            # URL解析缓存
            cursor.execute("SELECT COUNT(*) FROM url_parse_cache")
            url_count = cursor.fetchone()[0]
            
            # z参数缓存
            cursor.execute("SELECT COUNT(*) FROM z_params_cache")
            z_param_count = cursor.fetchone()[0]
            
            db_size = db_path.stat().st_size
            
            print(f"\n数据库缓存 ({db_path.name}):")
            print(f"  搜索缓存记录: {search_count}")
            print(f"  URL解析缓存记录: {url_count}")
            print(f"  z参数缓存记录: {z_param_count}")
            print(f"  数据库大小: {db_size / 1024 / 1024:.2f} MB")
            
            conn.close()
        except Exception as e:
            print(f"\n数据库缓存: 读取失败 - {e}")
    else:
        print(f"\n数据库缓存: 文件不存在")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "info":
            show_cache_info()
        elif command == "all":
            clear_all()
        elif command == "m3u8":
            clear_m3u8_cache()
        elif command == "db":
            clear_database_cache()
        else:
            print(f"未知命令: {command}")
            print("\n用法:")
            print("  python clear_cache.py info    # 显示缓存信息")
            print("  python clear_cache.py all      # 清理所有缓存")
            print("  python clear_cache.py m3u8    # 只清理m3u8文件缓存")
            print("  python clear_cache.py db      # 只清理数据库缓存")
    else:
        # 交互式菜单
        print("\n缓存清理工具")
        print("=" * 60)
        print("1. 显示缓存信息")
        print("2. 清理所有缓存")
        print("3. 只清理m3u8文件缓存")
        print("4. 只清理数据库缓存")
        print("0. 退出")
        print("=" * 60)
        
        choice = input("\n请选择操作 (0-4): ").strip()
        
        if choice == "1":
            show_cache_info()
        elif choice == "2":
            clear_all()
        elif choice == "3":
            print("\n清理m3u8文件缓存...")
            clear_m3u8_cache()
        elif choice == "4":
            print("\n清理数据库缓存...")
            clear_database_cache()
        elif choice == "0":
            print("退出")
        else:
            print("无效的选择")
