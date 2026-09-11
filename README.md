# xhs-studio

小红书笔记**备份**与**发布**工作台：把自己账号下的笔记（图片 / 视频 + 标题、正文、话题、互动数据）批量下载到本地，按标题搜索，以及从本地发布图文 / 视频笔记。提供 Streamlit 图形界面和命令行两种用法。

基于 [ReaJason/xhs](https://github.com/ReaJason/xhs) 的 `XhsClient` 封装，感谢原作者。

> 仅用于备份、管理**自己账号**的内容。请遵守小红书的服务条款，控制请求频率，不要用于抓取他人数据。

## 为什么有这个项目

`xhs` 库主站接口的 `x-s` 签名需要浏览器 JS 生成，纯 Python 内置签名已经不能用（返回 `{'code': -1}`），而原库示例依赖 Playwright 注入 `stealth.min.js` 调用页面函数签名，比较脆弱。本项目换了一条更稳的路：

| 功能 | 做法 | 需要签名？ |
|---|---|---|
| 笔记列表（首屏） | 抓个人主页 HTML 里的 `__INITIAL_STATE__` | 否 |
| 笔记列表（全部） | Playwright 打开主页自动滚动，截获页面自己发出的 `/user_posted` 响应 | 否（浏览器自己签） |
| 笔记详情 / 下载 | `get_note_by_id_from_html` 解析笔记页 HTML | 否 |
| 发布图文 / 视频 | 创作者平台接口 + 库内置签名 | 内置签名实测可用 |

另外修正了两个实际问题：话题必须在正文里写 `#话题名[话题]#` 标记才会显示；下载时同时保存文字内容。

## 安装

```bash
git clone https://github.com/<you>/xhs-studio.git
cd xhs-studio
pip install -r requirements.txt
playwright install chromium        # 只有"完整刷新"（翻页取全部笔记）需要
```

## 使用

### 1. 获取 Cookie

浏览器登录 `xiaohongshu.com`，并且**也登录一次** `creator.xiaohongshu.com`（创作者平台，发布功能和自动识别 user_id 依赖它的 cookie），然后开发者工具 → Network → 任意请求 → Request Headers → 复制整个 `Cookie`。

Cookie 只保存在本机 `~/.xhs-studio/config.json`，已在 `.gitignore` 里。

### 2. 图形界面

```bash
streamlit run app.py
```

- **设置**：粘贴 Cookie → 保存（自动识别 user_id）→ 测试连接
- **笔记**：快速刷新（首屏）/ 完整刷新（翻页取全部）→ 搜索 → 勾选 → 下载
- **发布**：图文 / 视频，支持话题、定时、私密发布（默认私密，确认无误再公开）

下载结构：

```
~/xhs-notes/
└── 笔记标题/
    ├── 笔记标题.txt      # 标题、正文、话题、点赞/收藏/评论数、note_id
    ├── 笔记标题_0.png
    └── ...               # 视频笔记为 笔记标题.mp4
```

### 3. 命令行

```bash
python -m xhs_studio.cli config --cookie "a1=...; web_session=...; ..."
python -m xhs_studio.cli list --all              # 翻页取全部并缓存
python -m xhs_studio.cli search 二分查找
python -m xhs_studio.cli download --title 二分查找
python -m xhs_studio.cli download --all

python -m xhs_studio.cli publish-image --title "72 法则" --desc "..." \
    --image rule72.jpg --topic 投资理财 --topic 复利            # 默认私密，加 --public 公开
python -m xhs_studio.cli publish-video --title "..." --desc "..." \
    --video a.mp4 --cover c.jpg --at "2026-09-12 10:00:00"
```

### 4. 作为库使用

```python
from xhs_studio.client import make_client
from xhs_studio.notes import fetch_notes_quick, download_note
from xhs_studio.publish import publish_image_note, resolve_topics

client = make_client(cookie)
notes = fetch_notes_quick(client, user_id)
download_note(client, notes[0], "~/xhs-notes")

topics = resolve_topics(client, ["投资理财"])
publish_image_note(client, "标题", "正文", ["a.jpg"], topics, is_private=True)
```

## 已知限制

- 主站需要签名的接口（搜索全站、评论、点赞等）本项目不提供。
- "完整刷新" 依赖 Playwright；若遇到验证码，在设置里关闭无头模式，在弹出的浏览器里手动过一次。
- 小红书接口随时可能变化；本项目在 2026-09 实测可用。

## License

MIT
