#!/usr/bin/env python3
"""
ACS Open Access 期刊下载器 - 使用 Scrapling 绕过 Cloudflare

直接下载 ACS 期刊中的 Open Access 文章，无需图书馆登录。
特点：
- 使用 Scrapling + 真实 Chrome 绕过 Cloudflare
- 自动识别 OA 文章
- 无需任何认证
- 支持断点续传
"""

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
import json
import re
import requests
from patchright.sync_api import sync_playwright
from scrapling import StealthyFetcher


class ACSOADownloader:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.fetch_timeout = 75
        self.download_root = self.base_dir / 'acs_oa_papers'
        self.remote_root = Path('/mnt/aliyun-papers/papers_oa')
        self.legacy_jmc_local_dir = self.base_dir / 'acs_papers'
        self.legacy_jmc_remote_dir = Path('/mnt/aliyun-papers/papers')
        self.download_dir = self.download_root
        self.remote_dir = self.remote_root
        self.browser_profile = self.base_dir / 'browser_profile_oa'
        self.cookies_file = self.base_dir / 'cookies_oa.json'
        self.openlist_base_url = 'http://127.0.0.1:5244'
        self.openlist_token_file = Path('/etc/openlist/admin_token')
        self.openlist_token = self.openlist_token_file.read_text().strip() if self.openlist_token_file.exists() else ''
        self.remote_api_base = '/aliyun/papers_oa'
        
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.remote_root.mkdir(parents=True, exist_ok=True)
        self.legacy_jmc_local_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_jmc_remote_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile.mkdir(parents=True, exist_ok=True)
        
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
        self.oa_found = 0
        self.ftr_found = 0
        self.uploaded = 0
        self.last_page_verdict = None
        self.last_page_reason = None
        self.last_page_url = None
        self.last_page_title = None
        self.last_page_html_bytes = 0
        self.last_page_signals = {}

    def normalize_filename(self, article):
        """从文章信息生成文件名"""
        doi = article.get('doi', '')
        if not doi:
            # 从 URL 提取
            doi = article['href'].split('/doi/pdf/')[-1].replace('/', '_')
        filename = doi.replace('/', '_')
        if '?' in filename:
            filename = filename.split('?')[0]
        return f'{filename}.pdf'

    def load_cookies(self):
        """加载保存的 cookies"""
        if self.cookies_file.exists():
            with open(self.cookies_file, 'r') as f:
                cookies = json.load(f)
            # Scrapling 期望 cookies 是列表格式
            if isinstance(cookies, list):
                return cookies
            # 如果是字典格式，转换回列表
            if isinstance(cookies, dict):
                return [{'name': k, 'value': v} for k, v in cookies.items()]
        return None

    def save_cookies(self, page):
        """保存 cookies"""
        try:
            # 从页面获取 cookies
            cookies = page.cookies
            with open(self.cookies_file, 'w') as f:
                json.dump(cookies, f)
            print(f'    ✓ Cookies 已保存')
        except Exception as e:
            print(f'    ! 保存 cookies 失败: {e}')

    def _fetch_with_timeout(self, url, wait_seconds=5):
        fetcher = StealthyFetcher()
        cookies = self.load_cookies()

        def _run():
            return fetcher.fetch(
                url,
                headless=False,
                solve_cloudflare=True,
                real_chrome=True,
                cookies=cookies,
                user_data_dir=str(self.browser_profile),
                wait_seconds=wait_seconds,
                timeout=45000,
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            try:
                return future.result(timeout=self.fetch_timeout)
            except FutureTimeoutError:
                future.cancel()
                raise TimeoutError(f'FETCH_TIMEOUT:{url}')

    def _reset_page_diagnostics(self):
        self.last_page_verdict = None
        self.last_page_reason = None
        self.last_page_url = None
        self.last_page_title = None
        self.last_page_html_bytes = 0
        self.last_page_signals = {}

    def _toc_fetch_strategies(self):
        return [
            {'name': 'scrapling_fast', 'wait_seconds': 5},
            {'name': 'scrapling_settle', 'wait_seconds': 10},
            {'name': 'scrapling_deep', 'wait_seconds': 15},
        ]

    def _should_retry_toc(self, reason):
        return reason in {
            'cloudflare_interstitial',
            'cloudflare_shell_page',
            'publisher_shell_without_article_list',
            'missing_article_list_markers',
            'html_too_small',
            'fetch_exception',
        }

    def _fetch_verified_toc_page(self, toc_url, journal_code, volume, issue):
        attempts = []
        last_page = None

        for strategy in self._toc_fetch_strategies():
            strategy_name = strategy['name']
            wait_seconds = strategy['wait_seconds']
            print(f'    策略: {strategy_name} (wait={wait_seconds}s)')

            self._reset_page_diagnostics()
            try:
                page = self._fetch_with_timeout(toc_url, wait_seconds=wait_seconds)
            except Exception as e:
                self.last_page_verdict = 'fetch_failed'
                self.last_page_reason = f'fetch_exception:{str(e)[:120]}'
                print(f'    ! 抓取异常: {self.last_page_reason}')
                attempts.append({
                    'strategy': strategy_name,
                    'verdict': self.last_page_verdict,
                    'reason': self.last_page_reason,
                    'html_bytes': 0,
                })
                continue

            last_page = page
            self.save_cookies(page)
            verdict, reason = self.verify_toc_page(page, toc_url, journal_code, volume, issue)
            self.last_page_verdict = verdict
            self.last_page_reason = reason

            print(f'    页面标题: {self.last_page_title or "<empty>"}')
            print(f'    最终 URL: {self.last_page_url or toc_url}')
            print(f'    HTML 大小: {self.last_page_html_bytes} bytes')
            print(f'    页面判定: {verdict} ({reason})')
            print(
                '    页面信号: '
                f'issue_items={self.last_page_signals.get("issue_item_count", 0)}, '
                f'oa_svg={int(bool(self.last_page_signals.get("has_open_access_svg")))}, '
                f'ftr_svg={int(bool(self.last_page_signals.get("has_free_to_read_svg")))}, '
                f'cloudflare={int(bool(self.last_page_signals.get("has_cloudflare")))}, '
                f'pb_page={int(bool(self.last_page_signals.get("has_pb_page")))}'
            )

            attempts.append({
                'strategy': strategy_name,
                'verdict': verdict,
                'reason': reason,
                'html_bytes': self.last_page_html_bytes,
            })
            self.last_page_signals['attempts'] = attempts

            if verdict == 'real_toc':
                print(f'    ✓ 页面获取成功 ({self.last_page_html_bytes} bytes)')
                return page

            if not self._should_retry_toc(reason):
                print('    ! 当前失败类型不适合继续重试，停止切换策略')
                break

            print('    ! 本策略未拿到真实 TOC，切换下一策略重试')

        if attempts:
            self.last_page_signals['attempts'] = attempts
        return None

    def verify_toc_page(self, page, toc_url, journal_code, volume, issue):
        """验证抓到的是否是真实 TOC 页面，而不是 Cloudflare/壳页/替代页。"""
        html = page.html_content or ''
        lowered = html.lower()
        current_url = getattr(page, 'url', None) or toc_url
        title = ''
        try:
            title = (page.title or '').strip()
        except Exception:
            title = ''

        issue_item_count = len(re.findall(r'<div class="issue-item clearfix">', html, re.IGNORECASE))
        signals = {
            'html_bytes': len(html),
            'issue_item_count': issue_item_count,
            'has_open_access_svg': 'open-access.svg' in lowered,
            'has_free_to_read_svg': 'free-to-read.svg' in lowered,
            'has_issue_item_title': 'issue-item_title' in lowered,
            'has_volume_label': f'volume {volume}'.lower() in lowered,
            'has_issue_label': f'issue {issue}'.lower() in lowered,
            'has_table_of_contents': 'table of contents' in lowered,
            'has_acs_publications': 'acs publications' in lowered,
            'has_cloudflare': 'cloudflare' in lowered,
            'has_security_verification': 'security verification' in lowered,
            'has_just_a_moment': 'just a moment' in lowered,
            'has_challenge': 'challenge' in lowered,
            'has_access_denial': 'access denial' in lowered,
            'has_pb_page': 'class="pb-page"' in lowered,
        }

        self.last_page_url = current_url
        self.last_page_title = title
        self.last_page_html_bytes = len(html)
        self.last_page_signals = signals

        if signals['html_bytes'] < 10000:
            return 'toc_not_verified', 'html_too_small'
        if signals['has_just_a_moment'] or signals['has_security_verification']:
            return 'toc_not_verified', 'cloudflare_interstitial'
        if signals['has_access_denial']:
            return 'toc_not_verified', 'access_denial'
        if signals['has_cloudflare'] and issue_item_count == 0:
            return 'toc_not_verified', 'cloudflare_shell_page'
        if signals['has_pb_page'] and issue_item_count == 0 and not signals['has_table_of_contents']:
            return 'toc_not_verified', 'publisher_shell_without_article_list'
        if issue_item_count > 0 or signals['has_issue_item_title']:
            return 'real_toc', 'article_list_detected'
        if signals['has_open_access_svg'] or signals['has_free_to_read_svg']:
            return 'real_toc', 'oa_marker_detected'
        if signals['has_table_of_contents'] and (signals['has_volume_label'] or signals['has_issue_label']):
            return 'real_toc', 'toc_markers_detected'
        return 'toc_not_verified', 'missing_article_list_markers'

    def get_toc_page(self, journal_code, volume, issue):
        """获取目录页面"""
        toc_url = f'https://pubs.acs.org/toc/{journal_code}/{volume}/{issue}'
        print(f'\n[获取目录页]')
        print(f'    URL: {toc_url}')

        page = self._fetch_verified_toc_page(toc_url, journal_code, volume, issue)
        if not page:
            print('    ✗ 页面未通过 TOC 真实性校验')
            return None
        return page

    def find_oa_articles(self, page):
        """在目录页中查找 OA 文章"""
        print(f'\n[查找可下载文章]')

        # ACS 网站使用图片标记开放文章:
        # - open-access.svg: 真正的 Open Access 文章
        # - free-to-read.svg: 限时免费文章
        oa_articles = []
        html = page.html_content or ''

        issue_blocks = re.findall(
            r'<div class="issue-item clearfix">.*?</div></div></div></div>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

        oa_count = 0
        ftr_count = 0

        for block in issue_blocks:
            doi_match = re.search(r'<input[^>]*value="(10\.[^"]+)"', block, re.IGNORECASE)
            if not doi_match:
                continue
            doi = doi_match.group(1)
            lowered = doi.lower()
            if '.issue-' in lowered or '/toc/' in lowered:
                continue

            article_type = None
            if 'open-access.svg' in block.lower():
                article_type = 'OA'
                oa_count += 1
            elif 'free-to-read.svg' in block.lower():
                article_type = 'FTR'
                ftr_count += 1
            else:
                continue

            title_match = re.search(r'<h3 class="issue-item_title"><a [^>]*>(.*?)</a></h3>', block, re.IGNORECASE | re.DOTALL)
            title = ''
            if title_match:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

            pdf_url = f'https://pubs.acs.org/doi/pdf/{doi}'
            oa_articles.append({
                'href': pdf_url,
                'title': title,
                'doi': doi,
                'type': article_type,
            })

        self.oa_found = oa_count
        self.ftr_found = ftr_count

        print(f'    找到 {self.oa_found} 篇 Open Access 文章')
        print(f'    找到 {self.ftr_found} 篇 Free to Read 文章')
        print(f'    共计 {len(oa_articles)} 篇可下载')

        return oa_articles

    def download_pdf(self, pdf_url, output_path, retries=2):
        """下载 PDF：优先在浏览器上下文内 fetch 真 PDF，失败时对 DOI 端点做回退重试。"""
        print(f'    下载: {pdf_url[:80]}...')

        alt_urls = [pdf_url]
        if '/doi/pdf/' in pdf_url:
            alt_urls.append(pdf_url.replace('/doi/pdf/', '/doi/epdf/'))
            alt_urls.append(pdf_url.replace('/doi/pdf/', '/doi/full/'))

        last_error = 'UNKNOWN'

        for candidate_url in alt_urls:
            for attempt in range(1, retries + 1):
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(
                            headless=False,
                            channel='chrome',
                            args=['--start-maximized'],
                        )
                        context = browser.new_context(no_viewport=True)
                        page = context.new_page()
                        try:
                            cookies = self.load_cookies() or []
                            if cookies:
                                cookie_payload = []
                                for c in cookies:
                                    name = c.get('name')
                                    value = c.get('value')
                                    if not name or value is None:
                                        continue
                                    cookie_payload.append({
                                        'name': name,
                                        'value': value,
                                        'domain': c.get('domain') or '.pubs.acs.org',
                                        'path': c.get('path') or '/',
                                        'httpOnly': bool(c.get('httpOnly', False)),
                                        'secure': bool(c.get('secure', True)),
                                        'sameSite': c.get('sameSite') or 'Lax',
                                    })
                                if cookie_payload:
                                    context.add_cookies(cookie_payload)

                            page.goto(candidate_url, wait_until='domcontentloaded', timeout=60000)
                            page.wait_for_timeout(2500)

                            html = page.content()
                            lowered = html.lower()
                            content_type = page.evaluate("document.contentType") or ''
                            if 'purchase' in lowered or 'subscribe' in lowered or 'access denial' in lowered:
                                return False, 'NOT_OA'
                            if 'turnstile' in lowered or 'cloudflare' in lowered or 'captcha' in lowered or 'security verification' in lowered or 'just a moment' in lowered:
                                last_error = 'CF_CHALLENGE'
                                continue

                            result = page.evaluate("""
                            async () => {
                              const tryUrls = [window.location.href];
                              if (window.location.href.includes('/doi/full/')) {
                                tryUrls.push(window.location.href.replace('/doi/full/', '/doi/pdf/'));
                                tryUrls.push(window.location.href.replace('/doi/full/', '/doi/epdf/'));
                              } else if (window.location.href.includes('/doi/epdf/')) {
                                tryUrls.push(window.location.href.replace('/doi/epdf/', '/doi/pdf/'));
                                tryUrls.push(window.location.href.replace('/doi/epdf/', '/doi/full/'));
                              } else if (window.location.href.includes('/doi/pdf/')) {
                                tryUrls.push(window.location.href.replace('/doi/pdf/', '/doi/epdf/'));
                                tryUrls.push(window.location.href.replace('/doi/pdf/', '/doi/full/'));
                              }

                              for (const u of tryUrls) {
                                try {
                                  const r = await fetch(u, {
                                    credentials: 'include',
                                    redirect: 'follow',
                                    headers: {
                                      'Accept': 'application/pdf,text/html;q=0.9,*/*;q=0.8'
                                    }
                                  });
                                  const finalUrl = r.url || u;
                                  const contentType = (r.headers.get('content-type') || '').toLowerCase();
                                  const textHint = contentType.includes('text/html') || contentType.includes('application/xhtml+xml');
                                  const buf = await r.arrayBuffer();
                                  const bytes = new Uint8Array(buf);
                                  let binary = '';
                                  const chunk = 0x8000;
                                  for (let i = 0; i < bytes.length; i += chunk) {
                                    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                                  }
                                  const prefix = binary.slice(0, 256);
                                  const looksLikePdf = binary.startsWith('%PDF-');
                                  const looksLikeHtml = /^\\s*</.test(prefix) || prefix.includes('<!DOCTYPE html') || prefix.includes('<html') || prefix.includes('citation_title') || prefix.includes('Access Denial');
                                  if (r.ok && looksLikePdf) {
                                    return {
                                      ok: true,
                                      status: r.status,
                                      url: finalUrl,
                                      requestedUrl: u,
                                      contentType,
                                      size: bytes.length,
                                      base64: btoa(binary)
                                    };
                                  }
                                  if (r.ok && looksLikeHtml) {
                                    return {
                                      ok: false,
                                      status: r.status,
                                      url: finalUrl,
                                      requestedUrl: u,
                                      contentType,
                                      size: bytes.length,
                                      reason: 'HTML_INSTEAD_OF_PDF',
                                      preview: prefix.slice(0, 200)
                                    };
                                  }
                                } catch (e) {}
                              }
                              return { ok: false, status: 0, contentType: '', size: 0, reason: 'FETCH_FAILED', base64: '' };
                            }
                            """)

                            if result.get('ok'):
                                fetch_content_type = (result.get('contentType') or '').lower()
                                raw = base64.b64decode(result['base64'])
                                if raw.startswith(b'%PDF-') and len(raw) > 50000:
                                    output_path.write_bytes(raw)
                                    return True, len(raw)
                                if 'pdf' not in fetch_content_type and 'pdf' not in content_type.lower():
                                    last_error = f'非 PDF: doc={content_type}, fetch={fetch_content_type}, url={result.get("url")}'
                                else:
                                    last_error = f'PDF 内容无效: url={result.get("url")}, size={len(raw)}'
                            else:
                                reason = result.get('reason') or f"FETCH_STATUS_{result.get('status')}"
                                if reason == 'HTML_INSTEAD_OF_PDF':
                                    preview = (result.get('preview') or '').replace('\n', ' ')[:120]
                                    last_error = f'HTML_INSTEAD_OF_PDF: final={result.get("url")}, ct={result.get("contentType")}, size={result.get("size")}, preview={preview}'
                                else:
                                    last_error = f'{reason}: final={result.get("url")}, ct={result.get("contentType")}, size={result.get("size")}'
                        finally:
                            context.close()
                            browser.close()
                except Exception as e:
                    msg = str(e)[:300]
                    lowered = msg.lower()
                    if 'turnstile' in lowered or 'cloudflare' in lowered or 'captcha' in lowered or 'timeout' in lowered or 'locator.bounding_box' in lowered or 'target page, context or browser has been closed' in lowered:
                        last_error = 'CF_TIMEOUT'
                    else:
                        last_error = msg

                if attempt < retries:
                    print(f'        ↻ 重试 {attempt}/{retries - 1}: {candidate_url[:70]}... ({last_error})')

        return False, last_error

    def _openlist_headers(self, extra=None):
        headers = {
            'Authorization': self.openlist_token,
        }
        if extra:
            headers.update(extra)
        return headers

    def ensure_remote_dir(self, api_path):
        if not self.openlist_token:
            raise RuntimeError('缺少 OpenList token')
        parts = [p for p in api_path.strip('/').split('/') if p]
        cur = ''
        for name in parts:
            parent = cur or '/'
            payload = {'path': parent, 'name': name}
            r = requests.post(
                f'{self.openlist_base_url}/api/fs/mkdir',
                headers=self._openlist_headers({'Content-Type': 'application/json'}),
                data=json.dumps(payload),
                timeout=30,
            )
            if r.status_code != 200:
                raise RuntimeError(f'mkdir_http_{r.status_code}:{parent}/{name}')
            cur = f'{cur}/{name}' if cur else f'/{name}'

    def remote_entry(self, api_dir, name):
        if not self.openlist_token:
            raise RuntimeError('缺少 OpenList token')
        r = requests.post(
            f'{self.openlist_base_url}/api/fs/list',
            headers=self._openlist_headers({'Content-Type': 'application/json'}),
            data=json.dumps({'path': api_dir, 'password': ''}),
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f'list_http_{r.status_code}:{api_dir}')
        data = r.json()
        for item in ((data.get('data') or {}).get('content') or []):
            if item.get('name') == name:
                return item
        return None

    def remote_file_ok(self, api_dir, name, min_size=100000):
        item = self.remote_entry(api_dir, name)
        if not item:
            return False
        try:
            size = int(item.get('size') or 0)
        except Exception:
            size = 0
        return size > min_size


    def existing_remote_locations(self, filename, min_size=100000):
        """Return remote API dirs where this normalized DOI filename already exists.

        OA backfill writes most journals under /aliyun/papers_oa/<journal>, while
        older/full-access JMC downloads live in /aliyun/papers. Check both families
        before issuing any ACS PDF request so an already archived paper is not
        downloaded again into papers_oa.
        """
        dirs = []
        seen = set()
        for api_dir in [
            getattr(self, 'remote_api_dir', None),
            '/aliyun/papers',
            f'{self.remote_api_base}/{getattr(self, "current_journal_code", "")}',
            f'{self.remote_api_base}/jmcmar',
            self.remote_api_base,
        ]:
            if not api_dir or api_dir in seen:
                continue
            seen.add(api_dir)
            try:
                if self.remote_file_ok(api_dir, filename, min_size=min_size):
                    dirs.append(api_dir)
            except Exception as e:
                print(f'        ! 查重目录失败 {api_dir}: {str(e)[:120]}')
        return dirs

    def existing_local_locations(self, filename, min_size=100000):
        """Return local cache paths where this normalized DOI filename already exists."""
        roots = [
            getattr(self, 'download_dir', None),
            self.download_root,
            self.download_root / getattr(self, 'current_journal_code', ''),
            self.download_root / 'jmcmar',
            self.legacy_jmc_local_dir,
        ]
        locations = []
        seen = set()
        for root in roots:
            if not root:
                continue
            path = Path(root) / filename
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                if path.exists() and path.stat().st_size > min_size:
                    locations.append(path)
            except OSError:
                pass
        return locations

    def upload_to_remote(self, local_path, remote_api_dir, remote_name):
        """通过 OpenList API 上传到云盘，不再依赖 rclone mount 可写性。"""
        try:
            if not local_path.exists():
                print(f'        ! 上传失败: 本地文件不存在: {local_path}')
                return False
            self.ensure_remote_dir(remote_api_dir)
            with open(local_path, 'rb') as f:
                r = requests.put(
                    f'{self.openlist_base_url}/api/fs/put',
                    headers=self._openlist_headers({
                        'File-Path': f'{remote_api_dir}/{remote_name}',
                        'Content-Type': 'application/octet-stream',
                    }),
                    data=f,
                    timeout=300,
                )
            if r.status_code != 200:
                print(f'        ! 上传失败: HTTP {r.status_code}')
                return False
            try:
                data = r.json()
                if data.get('code') != 200:
                    print(f'        ! 上传失败: API code={data.get("code")}')
                    return False
            except Exception:
                pass
            return self.remote_file_ok(remote_api_dir, remote_name, min_size=1000)
        except Exception as e:
            print(f'        ! 上传失败: {str(e)[:160]}')
            return False

    def download_issue(self, journal_code, volume, issue):
        """下载指定卷期的 OA 文章"""
        
        journal_names = {
            'jmcmar': 'Journal of Medicinal Chemistry',
            'jacsat': 'Journal of the American Chemical Society',
            'anano': 'ACS Nano',
            'esthag': 'Environmental Science & Technology',
            'chreay': 'Chemical Reviews',
            'mpohbp': 'Molecular Pharmaceutics',
            'jmcbdf': 'Journal of Medicinal Chemistry Letters',
        }
        self.current_journal_code = journal_code
        journal_name = journal_names.get(journal_code, journal_code)
        if journal_code == 'jmcmar':
            # 与原 JMC 下载器并到同一套目录，便于直接跳过已下载文件
            self.download_dir = self.legacy_jmc_local_dir
            self.remote_dir = self.legacy_jmc_remote_dir
            self.remote_api_dir = '/aliyun/papers'
        else:
            self.download_dir = self.download_root / journal_code
            self.remote_dir = self.remote_root / journal_code
            self.remote_api_dir = f'{self.remote_api_base}/{journal_code}'
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.remote_dir.mkdir(parents=True, exist_ok=True)
        
        print('=' * 60)
        print('ACS Open Access 期刊下载器')
        print(f'期刊: {journal_name} ({journal_code})')
        print(f'卷期: Volume {volume}, Issue {issue}')
        print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print('=' * 60)
        
        # 获取目录页
        page = self.get_toc_page(journal_code, volume, issue)
        if not page:
            print('\n✗ 无法获取目录页')
            print(json.dumps({
                'result_type': 'issue_summary',
                'journal': journal_code,
                'volume': volume,
                'issue': issue,
                'page_verdict': self.last_page_verdict,
                'page_reason': self.last_page_reason,
                'page_url': self.last_page_url,
                'page_title': self.last_page_title,
                'page_html_bytes': self.last_page_html_bytes,
                'page_signals': self.last_page_signals,
                'oa_found': self.oa_found,
                'ftr_found': self.ftr_found,
                'downloaded': self.downloaded,
                'uploaded': self.uploaded,
                'skipped': self.skipped,
                'failed': self.failed,
                'decision': 'toc_not_verified',
            }, ensure_ascii=False))
            return False
        
        # 查找 OA 文章
        oa_articles = self.find_oa_articles(page)
        
        if not oa_articles:
            print('\n该期无 Open Access 文章（已通过 TOC 真实性校验）')
            print(json.dumps({
                'result_type': 'issue_summary',
                'journal': journal_code,
                'volume': volume,
                'issue': issue,
                'page_verdict': self.last_page_verdict,
                'page_reason': self.last_page_reason,
                'page_url': self.last_page_url,
                'page_title': self.last_page_title,
                'page_html_bytes': self.last_page_html_bytes,
                'page_signals': self.last_page_signals,
                'oa_found': self.oa_found,
                'ftr_found': self.ftr_found,
                'downloaded': self.downloaded,
                'uploaded': self.uploaded,
                'skipped': self.skipped,
                'failed': self.failed,
                'decision': 'no_oa_confirmed',
            }, ensure_ascii=False))
            return True
        
        print(f'\n[下载 OA PDF] 共 {len(oa_articles)} 篇')
        
        for i, article in enumerate(oa_articles):
            filename = self.normalize_filename(article)
            local_path = self.download_dir / filename
            remote_path = self.remote_dir / filename
            remote_api_dir = self.remote_api_dir
            
            article_type = article.get('type', 'OA')
            type_label = '[OA]' if article_type == 'OA' else '[FTR]'
            
            print(f'\n    [{i+1}/{len(oa_articles)}] {type_label} {filename[:65]}')
            if article['title']:
                print(f'        标题: {article["title"][:60]}...')
            
            # 先做“下载前”存在性判断：文件名由 DOI 归一化而来。
            # 注意：历史/全文下载目录是 /aliyun/papers，OA 目录是 /aliyun/papers_oa/<journal>。
            # 两边都要查，否则 papers 里已有的文章会被重复下载进 papers_oa。
            remote_locations = self.existing_remote_locations(filename, min_size=100000)
            local_locations = self.existing_local_locations(filename, min_size=100000)
            remote_ok = bool(remote_locations)
            local_ok = bool(local_locations)

            if remote_ok and local_ok:
                print(f'        ↷ 跳过：云盘已存在于 {", ".join(remote_locations)}；清理本地副本')
                for stale_path in local_locations:
                    try:
                        stale_path.unlink()
                    except FileNotFoundError:
                        pass
                self.skipped += 1
                continue

            if local_ok and not remote_ok:
                source_path = local_locations[0]
                if source_path != local_path:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(source_path.read_bytes())
                if self.upload_to_remote(local_path, remote_api_dir, filename):
                    print(f'        ↑ 已补传云盘 ({local_path.stat().st_size / 1024 / 1024:.2f} MB)')
                    self.uploaded += 1
                    for stale_path in set(local_locations + [local_path]):
                        try:
                            stale_path.unlink()
                            print(f'        🧹 已清理本地副本: {stale_path}')
                        except FileNotFoundError:
                            pass
                continue

            if remote_ok and not local_ok:
                print(f'        ↷ 跳过：云盘已存在于 {", ".join(remote_locations)}')
                self.skipped += 1
                continue
            
            # 下载
            success, result = self.download_pdf(article['href'], local_path)
            
            if success:
                print(f'        ✓ 已下载 ({result / 1024 / 1024:.2f} MB)')
                self.downloaded += 1
                if self.upload_to_remote(local_path, remote_api_dir, filename):
                    print('        ↑ 已上传云盘')
                    self.uploaded += 1
                    try:
                        local_path.unlink()
                        print('        🧹 已清理本地副本')
                    except FileNotFoundError:
                        pass
            elif result == 'NOT_OA':
                print('        ✗ 非 OA 文章，需要订阅')
            elif result in ('CF_CHALLENGE', 'CF_TIMEOUT'):
                print(f'        ! Cloudflare/Turnstile 挑战未解开，跳过: {result}')
                self.failed += 1
            elif result == 'PDF_EMBEDDER_HTML':
                print('        ! 命中了 Chrome PDF embedder HTML，不是真 PDF bytes，先跳过')
                self.failed += 1
            else:
                print(f'        ✗ 下载失败: {result}')
                self.failed += 1
        
        # 打印统计
        print('\n' + '=' * 60)
        print('处理完成')
        print('=' * 60)
        print(f'Open Access: {self.oa_found}')
        print(f'Free to Read: {self.ftr_found}')
        print(f'下载成功: {self.downloaded}')
        print(f'上传成功: {self.uploaded}')
        print(f'跳过: {self.skipped}')
        print(f'失败: {self.failed}')
        print(f'本地目录: {self.download_dir}')
        
        total_size = sum(f.stat().st_size for f in self.download_dir.glob('*.pdf'))
        print(f'本地总大小: {total_size / 1024 / 1024:.2f} MB')
        print(json.dumps({
            'result_type': 'issue_summary',
            'journal': journal_code,
            'volume': volume,
            'issue': issue,
            'page_verdict': self.last_page_verdict,
            'page_reason': self.last_page_reason,
            'page_url': self.last_page_url,
            'page_title': self.last_page_title,
            'page_html_bytes': self.last_page_html_bytes,
            'page_signals': self.last_page_signals,
            'oa_found': self.oa_found,
            'ftr_found': self.ftr_found,
            'downloaded': self.downloaded,
            'uploaded': self.uploaded,
            'skipped': self.skipped,
            'failed': self.failed,
            'decision': 'downloads_attempted_or_completed',
        }, ensure_ascii=False))
        
        return True


def main():
    parser = argparse.ArgumentParser(description='ACS Open Access 期刊下载器')
    parser.add_argument('journal', nargs='?', default='jmcmar', help='期刊代码')
    parser.add_argument('--volume', '-v', type=int, required=True, help='卷号')
    parser.add_argument('--issue', '-i', type=int, required=True, help='期号')
    
    args = parser.parse_args()
    
    downloader = ACSOADownloader()
    downloader.download_issue(args.journal, args.volume, args.issue)


if __name__ == '__main__':
    main()
