#!/usr/bin/env python3
"""
ACS 期刊下载器 - 主程序
通过机构图书馆下载 ACS 期刊论文

使用方法:
    python acs_downloader.py [期刊代码]

示例:
    python acs_downloader.py jmcmar    # 下载 Journal of Medicinal Chemistry
    python acs_downloader.py jacsat    # 下载 JACS
"""

import asyncio
import os
import sys
import yaml
import base64
import argparse
from pathlib import Path
from datetime import datetime
from patchright.async_api import async_playwright

class ACSDownloader:
    """ACS 期刊下载器"""
    
    def __init__(self, config_path=None):
        # 加载配置
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # 设置路径
        self.base_dir = Path(__file__).parent
        self.download_dir = self.base_dir / self.config['download']['output_dir']
        self.profile_dir = self.base_dir / self.config['browser']['profile_dir']
        
        # 创建目录
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
    
    async def login_library(self, page):
        """登录图书馆"""
        print("\n[登录图书馆]")
        
        login_url = self.config['library']['login_url']
        username = self.config['library']['username']
        password = self.config['library']['password']
        
        await page.goto(login_url, timeout=30000)
        await asyncio.sleep(2)
        
        # 检查是否已登录
        if '退出' in await page.content():
            print("    ✓ 已登录")
            return True
        
        # 填写登录表单
        print(f"    用户名: {username}")
        await page.fill('input[name="username"]', username)
        await asyncio.sleep(1)
        
        print(f"    密码: {'*' * len(password)}")
        await page.fill('input[name="password"]', password)
        await asyncio.sleep(1)
        
        # 提交
        await page.click('input[name="Submit"]')
        await asyncio.sleep(3)
        
        # 检查登录状态
        if '退出' in await page.content() or username in await page.content():
            print("    ✓ 登录成功")
            return True
        else:
            print("    ✗ 登录失败")
            return False
    
    async def enter_acs(self, page, browser):
        """通过两步验证进入 ACS"""
        print("\n[进入 ACS]")
        
        acs_entry_url = self.config['library']['acs_entry_url']
        await page.goto(acs_entry_url, timeout=30000)
        await asyncio.sleep(3)
        
        # 第一步
        step1 = await page.query_selector('input[value="第一步点我"]')
        if step1:
            print("    执行第一步验证...")
            await step1.click()
            await asyncio.sleep(3)
            
            # 关闭可能的新窗口
            for p in browser.pages[1:]:
                await p.close()
            
            await page.goto(acs_entry_url, timeout=30000)
            await asyncio.sleep(3)
        
        # 第二步
        step2 = await page.query_selector('input[value="第二步点我"]')
        if step2:
            print("    执行第二步验证...")
            await step2.click()
            await asyncio.sleep(5)
            
            # 处理 SSO
            if 'idp.iitm.ac.in' in page.url or 'sso' in page.url.lower():
                print("    处理 SSO 同意...")
                
                # 选择记住同意
                remember = await page.query_selector('input[value="_shib_idp_rememberConsent"]')
                if remember:
                    await remember.click()
                    await asyncio.sleep(1)
                
                # 点击接受
                accept = await page.query_selector('input[name="_eventId_proceed"]')
                if accept:
                    await accept.click()
                    await asyncio.sleep(8)
        
        # 检查是否进入 ACS
        if 'acs.org' in page.url:
            print("    ✓ 已进入 ACS")
            return True
        else:
            print(f"    ✗ 未能进入 ACS，当前 URL: {page.url}")
            return False
    
    async def get_pdf_links(self, page, journal_code, volume=None, issue=None):
        """获取期刊指定期的 PDF 链接
        
        Args:
            page: Playwright page 对象
            journal_code: 期刊代码
            volume: 卷号 (None = 最新一期)
            issue: 期号 (None = 最新一期)
        """
        print(f"\n[获取 PDF 链接]")
        
        # 构建URL
        if volume and issue:
            toc_url = f"https://pubs.acs.org/toc/{journal_code}/{volume}/{issue}"
            print(f"    指定期: Volume {volume}, Issue {issue}")
        else:
            toc_url = f"https://pubs.acs.org/toc/{journal_code}/current"
            print(f"    最新一期")
        
        print(f"    访问: {toc_url}")
        
        await page.goto(toc_url, timeout=30000)
        await asyncio.sleep(5)
        
        # 检查是否成功访问
        current_url = page.url
        if 'error' in current_url.lower() or 'not found' in (await page.evaluate('document.body.innerText')).lower():
            print(f"    ✗ 无法访问该期: {current_url}")
            return []
        
        # 获取 PDF 链接
        pdf_links = await page.evaluate('''
            Array.from(document.querySelectorAll('a[href*="/doi/pdf/"]')).map(a => ({
                href: a.href,
                text: a.innerText.trim()
            })).filter(l => l.href.length > 0)
        ''')
        
        print(f"    找到 {len(pdf_links)} 个 PDF 链接")
        
        return pdf_links
    
    async def download_pdf(self, page, url, output_path):
        """下载单个 PDF"""
        try:
            await page.goto(url, timeout=60000)
            await asyncio.sleep(3)
            
            # 检查内容类型
            content_type = await page.evaluate('document.contentType')
            
            if content_type != 'application/pdf':
                return False, f"非 PDF: {content_type}"
            
            # 使用 JavaScript 获取 PDF Blob
            pdf_base64 = await page.evaluate('''
                async () => {
                    try {
                        const response = await fetch(window.location.href);
                        const blob = await response.blob();
                        
                        if (blob.size < 50000) {
                            return {error: 'file_too_small', size: blob.size};
                        }
                        
                        return new Promise((resolve) => {
                            const reader = new FileReader();
                            reader.onloadend = () => {
                                const base64 = reader.result.split(',')[1];
                                resolve({data: base64, size: blob.size});
                            };
                            reader.onerror = () => resolve({error: 'read_failed'});
                            reader.readAsDataURL(blob);
                        });
                    } catch (e) {
                        return {error: e.message};
                    }
                }
            ''')
            
            if pdf_base64.get('error'):
                return False, pdf_base64['error']
            
            if pdf_base64.get('data'):
                # 解码并保存
                data = base64.b64decode(pdf_base64['data'])
                
                with open(output_path, 'wb') as f:
                    f.write(data)
                
                return True, len(data)
            
            return False, "无法获取 PDF 数据"
            
        except Exception as e:
            return False, str(e)[:80]
    
    async def download_journal(self, journal_code=None, volume=None, issue=None):
        """下载期刊指定期
        
        Args:
            journal_code: 期刊代码 (如 jmcmar)
            volume: 卷号 (None = 最新一期)
            issue: 期号 (None = 最新一期)
        """
        if journal_code is None:
            journal_code = self.config['acs']['default_journal']
        
        if volume is None:
            volume = self.config['acs'].get('default_volume')
        if issue is None:
            issue = self.config['acs'].get('default_issue')
        
        journal_name = self.config['acs']['journals'].get(journal_code, journal_code)
        
        print("=" * 60)
        print(f"ACS 期刊下载器")
        print(f"期刊: {journal_name} ({journal_code})")
        if volume and issue:
            print(f"卷期: Volume {volume}, Issue {issue}")
        else:
            print(f"卷期: 最新一期")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        async with async_playwright() as p:
            # 启动浏览器
            print("\n[启动浏览器]")
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.config['browser']['headless'],
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )
            
            page = browser.pages[0] if browser.pages else await browser.new_page()
            
            try:
                # 登录
                if not await self.login_library(page):
                    print("\n✗ 登录失败，退出")
                    return False
                
                # 进入 ACS
                if not await self.enter_acs(page, browser):
                    print("\n✗ 无法进入 ACS，退出")
                    return False
                
                # 获取 PDF 链接
                pdf_links = await self.get_pdf_links(page, journal_code, volume, issue)
                
                if not pdf_links:
                    print("\n✗ 未找到 PDF 链接")
                    return False
                
                # 下载 PDF
                print(f"\n[下载 PDF] (共 {len(pdf_links)} 篇)")
                
                for i, link in enumerate(pdf_links):
                    # 提取 DOI
                    doi = link['href'].split('/doi/pdf/')[-1].replace('/', '_')
                    if '?' in doi:
                        doi = doi.split('?')[0]
                    
                    filename = f"{doi}.pdf"
                    output_path = self.download_dir / filename
                    
                    # 检查是否已下载
                    if output_path.exists():
                        size = output_path.stat().st_size
                        if size > 100000:
                            print(f"    [{i+1}/{len(pdf_links)}] 已存在: {filename[:50]}...")
                            self.skipped += 1
                            continue
                    
                    print(f"\n    [{i+1}/{len(pdf_links)}] {doi[:50]}...")
                    
                    success, result = await self.download_pdf(page, link['href'], output_path)
                    
                    if success:
                        print(f"        ✓ 已保存 ({result:,} bytes = {result/1024/1024:.2f} MB)")
                        self.downloaded += 1
                    else:
                        print(f"        ✗ {result}")
                        self.failed += 1
                    
                    await asyncio.sleep(self.config['download']['delay'])
                
                # 汇总
                print("\n" + "=" * 60)
                print("下载完成")
                print("=" * 60)
                print(f"成功: {self.downloaded}")
                print(f"跳过: {self.skipped}")
                print(f"失败: {self.failed}")
                print(f"目录: {self.download_dir}")
                
                # 计算总大小
                total_size = sum(
                    f.stat().st_size 
                    for f in self.download_dir.glob('*.pdf')
                )
                print(f"总大小: {total_size/1024/1024:.2f} MB")
                
                return True
                
            finally:
                await asyncio.sleep(5)
                await browser.close()


async def main():
    parser = argparse.ArgumentParser(description='ACS 期刊下载器')
    parser.add_argument('journal', nargs='?', default=None,
                        help='期刊代码 (如 jmcmar, jacsat, anano)')
    parser.add_argument('--volume', '-v', type=int, default=None,
                        help='卷号 (Volume)')
    parser.add_argument('--issue', '-i', type=int, default=None,
                        help='期号 (Issue)')
    parser.add_argument('--config', '-c', default=None,
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    downloader = ACSDownloader(args.config)
    await downloader.download_journal(args.journal, args.volume, args.issue)


if __name__ == "__main__":
    asyncio.run(main())
