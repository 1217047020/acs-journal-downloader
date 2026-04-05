#!/bin/bash
# ACS 期刊下载器 - 安装脚本

set -e

echo "安装 ACS 期刊下载器..."

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 需要安装 Python 3"
    exit 1
fi

# 安装依赖
echo "安装 Python 依赖..."
pip install -r requirements.txt

# 安装浏览器
echo "安装 Chromium 浏览器..."
playwright install chromium

# 创建目录
mkdir -p acs_papers browser_profile

echo ""
echo "安装完成！"
echo ""
echo "使用方法:"
echo "  python acs_downloader.py              # 下载 JMC 最新一期"
echo "  python acs_downloader.py jacsat       # 下载 JACS 最新一期"
echo ""
echo "请先编辑 config.yaml 配置图书馆账号"
