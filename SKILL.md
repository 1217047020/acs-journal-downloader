# ACS Journal Downloader

通过机构图书馆下载 ACS 期刊论文。

## 功能

- 自动登录图书馆账号
- 通过 Shibboleth SSO 认证进入 ACS
- 下载期刊最新一期的所有论文 PDF
- 支持自定义期刊代码

## 使用方法

```
下载 JMC 最新一期：acs-downloader

下载其他期刊：acs-downloader <期刊代码>

例如：
- JMC: acs-downloader jmcmar
- JACS: acs-downloader jacsat
- ACS Nano: acs-downador anano
```

## 配置

首次使用需要在 `config.yaml` 中配置图书馆账号：

```yaml
library:
  url: "http://www.90tsg.com"
  username: "your_card_number"
  password: "your_password"
  acs_entry_id: "5068"  # ACS 入口 ID
```

## 依赖

- Python 3.8+
- patchright (Playwright fork)
- xvfb (虚拟显示)

## 安装

```bash
pip install patchright
playwright install chromium
```
