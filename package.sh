#!/bin/bash
# 打包 ACS 下载器

set -e

VERSION="1.0.0"
PACKAGE_NAME="acs-downloader-${VERSION}"

echo "打包 ACS 下载器 v${VERSION}..."

# 创建临时目录
TMP_DIR="/tmp/${PACKAGE_NAME}"
rm -rf "${TMP_DIR}"
mkdir -p "${TMP_DIR}"

# 复制文件
cp acs_downloader.py "${TMP_DIR}/"
cp config.yaml "${TMP_DIR}/"
cp requirements.txt "${TMP_DIR}/"
cp install.sh "${TMP_DIR}/"
cp README.md "${TMP_DIR}/"
cp SKILL.md "${TMP_DIR}/"

# 清理配置文件中的敏感信息
sed -i 's/username: ".*"/username: "YOUR_CARD_NUMBER"/' "${TMP_DIR}/config.yaml"
sed -i 's/password: ".*"/password: "YOUR_PASSWORD"/' "${TMP_DIR}/config.yaml"
sed -i 's/acs_entry_url: ".*"/acs_entry_url: "YOUR_LIBRARY_ACS_ENTRY_URL"/' "${TMP_DIR}/config.yaml"

# 创建目录结构
mkdir -p "${TMP_DIR}/acs_papers"
mkdir -p "${TMP_DIR}/browser_profile"

# 打包
cd /tmp
tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}"

# 移动到输出目录
mv "${PACKAGE_NAME}.tar.gz" /root/clawd/skills/acs-downloader/

# 清理
rm -rf "${TMP_DIR}"

echo ""
echo "打包完成: ${PACKAGE_NAME}.tar.gz"
echo "位置: /root/clawd/skills/acs-downloader/${PACKAGE_NAME}.tar.gz"
echo ""
echo "在其他机器上使用:"
echo "  1. 复制 ${PACKAGE_NAME}.tar.gz 到目标机器"
echo "  2. 解压: tar -xzf ${PACKAGE_NAME}.tar.gz"
echo "  3. 进入目录: cd ${PACKAGE_NAME}"
echo "  4. 编辑 config.yaml 配置图书馆账号"
echo "  5. 安装: ./install.sh"
echo "  6. 运行: python acs_downloader.py"
