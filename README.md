# ACS Journal Downloader

通过机构图书馆下载 ACS 期刊论文，也支持直接下载 ACS Open Access / Free to Read 文章。

## 安装依赖

建议使用独立虚拟环境，避免污染系统 Python：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -i https://pypi.org/simple -r requirements.txt
python -m patchright install chromium
```

## 运行环境要求

这个下载器按 **有头浏览器** 流程设计，默认应保持 `headless: false`。

### 本地桌面环境

如果机器本身有图形桌面，确保存在可用的 X server，并且 `DISPLAY` 已设置。

### 无桌面的 Linux 服务器

在纯命令行服务器上，必须提供虚拟显示环境，否则浏览器会直接启动失败。

推荐启动方式：

```bash
xvfb-run -a .venv/bin/python acs_downloader.py jmcmar --volume 69 --issue 6
```

也可以手动启动 Xvfb：

```bash
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
.venv/bin/python acs_downloader.py jmcmar --volume 69 --issue 6
```

如果看到类似报错：

- `Missing X server or $DISPLAY`
- `The platform failed to initialize`

优先把它视为**显示环境问题**，而不是 ACS、图书馆登录、SSO 或选择器问题。

## 配置

编辑 `config.yaml` 文件：

```yaml
library:
  username: "your_card_number"
  password: "your_password"
  acs_entry_url: "your_library_acs_entry_url"
```

## 使用方法

### 1) 机构图书馆登录版下载器

```bash
# 下载最新一期
python acs_downloader.py
python acs_downloader.py jmcmar

# 下载指定期 (Volume 69, Issue 6)
python acs_downloader.py jmcmar --volume 69 --issue 6
python acs_downloader.py jmcmar -v 69 -i 6

# 下载其他期刊
python acs_downloader.py jacsat              # JACS 最新一期
python acs_downloader.py jacsat -v 145 -i 1  # JACS Volume 145, Issue 1
python acs_downloader.py anano               # ACS Nano 最新一期

# 指定配置文件
python acs_downloader.py --config /path/to/config.yaml
```

在服务器上，优先使用：

```bash
xvfb-run -a .venv/bin/python acs_downloader.py jmcmar --volume 69 --issue 6
```

### 2) ACS Open Access / Free to Read 下载器

这个版本不走图书馆登录，直接从 ACS 目录页识别 OA / FTR 文章，再用浏览器上下文内的 `fetch + arrayBuffer/base64` 抽取真 PDF。

```bash
# 下载指定期
python acs_oa_downloader.py jmcmar -v 68 -i 1
python acs_oa_downloader.py jmcmar --volume 69 --issue 7

# 服务器推荐启动方式
xvfb-run -a .venv/bin/python acs_oa_downloader.py jmcmar -v 69 -i 7
```

当前 OA 下载器特性：

- 按单篇 `issue-item` 区块识别 OA / FTR，避免 DOI 错配
- 下载前先检查云端是否已存在同名 PDF，已存在则跳过
- 使用持久化 Chrome + 页面内 JS `fetch` 抓取真实 PDF bytes
- 落盘前校验文件头 `%PDF-`，避免把 HTML / Chrome PDF embedder 壳误当成成功
- 上传成功后自动删除本地副本

## 支持的期刊代码

| 代码 | 期刊名称 |
|------|----------|
| jmcmar | Journal of Medicinal Chemistry |
| jacsat | Journal of the American Chemical Society |
| anano | ACS Nano |
| esthag | Environmental Science & Technology |
| chreay | Chemical Reviews |

更多期刊代码请参考 ACS 官网。

## 输出

- 图书馆登录版下载器：PDF 默认保存在 `acs_papers/`
- OA 下载器：运行时会先落到 `acs_oa_papers/`，再上传到远端；默认文件名格式为 DOI 归一化后的 `DOI.pdf`

## 注意事项

1. 图书馆登录版首次运行需要登录图书馆账号
2. OA 下载器虽然不需要图书馆认证，但仍依赖真实浏览器环境，服务器上建议配合 `xvfb-run -a`
3. 浏览器配置文件和 cookies 都属于本地运行态数据，不应提交到 Git 仓库
4. 如果下载中断，重新运行会跳过已下载或远端已存在的文件
5. 遇到 SSO、验证码、Cloudflare、Turnstile、浏览器无法启动或 PDF 假下载问题时，优先参考 `references/troubleshooting.md`
6. 真正的论文 PDF 必须通过浏览器内认证状态下的 `fetch + blob + base64` 保存，不要用 `page.pdf()` 代替真实下载
