# ACS Journal Downloader

通过机构图书馆下载 ACS 期刊论文。

## 安装依赖

```bash
pip install patchright pyyaml
playwright install chromium
```

## 配置

编辑 `config.yaml` 文件：

```yaml
library:
  username: "your_card_number"
  password: "your_password"
  acs_entry_url: "your_library_acs_entry_url"
```

## 使用方法

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

PDF 文件保存在 `acs_papers/` 目录，文件名格式为 `DOI.pdf`。

## 注意事项

1. 首次运行需要登录图书馆账号
2. 浏览器配置文件保存在 `browser_profile/` 目录
3. 如果下载中断，重新运行会跳过已下载的文件
