# AgentDeck 开源发布执行报告（v01）

本报告记录 2026-09-25 把 AgentDeck 从本地开发目录整理为公开 GitHub 仓库的完整过程。
所有结论都来自本次实际执行与命令输出，未做推测性描述。

---

## 1. Environment（执行环境）

| 组件 | 版本 |
| --- | --- |
| 操作系统 | Windows 10.0.26200（x64） |
| Python | 3.10.11（项目内 `.venv`） |
| PySide6 | 6.11.2 |
| pytest | 9.1.1 |
| PyInstaller | 6.22.3 |
| Git | 2.55.0.windows.5 |
| GitHub CLI | 2.101.0（本次通过 `winget install --id GitHub.cli` 安装） |

项目根目录：`C:\Users\lihao\Desktop\prompt lab\AgentDeck`
（该目录就是 Git 仓库根目录，未在父目录执行 `git init`，也没有嵌套仓库。）

### 网络环境说明

本机系统代理处于开启状态（`127.0.0.1:10808`），但 `gh` 与 `git` 默认**不走**系统代理，
而本机直连 `github.com` 会超时（`api.github.com` 直连可用，`github.com` 不可用）。
因此本次的登录与推送都显式注入代理后执行：

```bash
export HTTPS_PROXY=http://127.0.0.1:10808
export HTTP_PROXY=http://127.0.0.1:10808
```

第一次 `gh auth login` 未带代理，失败于：

```
Post "https://github.com/login/oauth/access_token": read tcp ...: wsarecv:
A connection attempt failed because the connected party did not properly respond ...
```

带代理重新发起后登录成功。**日后在本机执行 `git push` 若遇到超时，按同样方式带上代理即可。**
本次未把代理写入 git 配置（避免代理关闭后影响其他操作），仅在命令行内临时注入。

---

## 2. Changes（本次改动）

### 2.1 新增文件

| 文件 | 说明 |
| --- | --- |
| `LICENSE` | MIT License，年份 2026。Copyright holder 取 `Haolun Li`——项目内原本没有任何作者署名，该名字依据本机 Git 全局身份（`user.name=lihaolun201003`、`user.email=lihaolun201003@gmail.com`）确定，未凭空创造 |
| `.gitignore` | 排除虚拟环境、构建产物、本机备份、运行数据、Python 缓存、编辑器配置 |
| `requirements-dev.txt` | 开发依赖：`-r requirements.txt` + `pytest>=7,<10` + `pyinstaller>=6.22,<7` |
| `THIRD_PARTY_NOTICES.md` | 第三方组件许可说明（PySide6 / Qt / PyInstaller） |
| `docs/reports/open_source_release_v01.md` | 本报告 |

### 2.2 修改文件

| 文件 | 改动 |
| --- | --- |
| `requirements.txt` | `PySide6>=6.6` → `PySide6>=6.6,<7`，避免上游大版本漂移 |
| `build.bat` | 不再无条件执行 `pip install --upgrade pyinstaller`；改为先检测 PyInstaller 是否可用，缺失时才从 `requirements-dev.txt` 安装。其余打包流程与产物路径保持不变，文件仍为纯 ASCII |
| `README.md` | 在保留原有全部内容的基础上补充：平台支持说明（仅 Windows）、环境要求表、不依赖 `Activate.ps1` 的安装方式、完整的「运行测试」章节、GitHub Releases 发布说明、「许可证与第三方组件」章节；目录结构补入新增文件；主图改用当前白色主题截图 |
| `docs/agentdeck_v01.md` | 修正过时内容：测试数量改为「完整自动化测试套件」；`theme.py` 职责与两处 `QPalette` 描述由「深色」改为「浅色」；设计取舍表中「无边框窗口」一条改为实际实现（原生标题栏 + 系统贴靠分屏）；目录结构补入 LICENSE / requirements-dev.txt / THIRD_PARTY_NOTICES.md |
| `docs/responsive-window.md` | 「68 个自动化用例通过」→「完整自动化测试套件通过」，避免每加一个测试就过时 |
| `src/ui/main_window.py` | 顶层类定义前补一个空行（PEP 8 E302）。全项目扫描未发现同类其他问题，未做任何其他格式化 |

### 2.3 截图处理

`tests/render_screenshots.py` 会真实启动程序并抓取 `01-main`～`06-context-menu` 六张截图。
原有 `01`～`06` 是深色主题时期的产物，与当前白色界面不符，本次**重新运行该脚本重新生成**，
六张图现在与当前实现一致（脚本同时验证了窗口可见、取得前台焦点、搜索框聚焦、热键注册成功、托盘可用）。

| 文件 | 处理 |
| --- | --- |
| `07-white-preview` / `08-white-settings` / `09-white-editor` / `10-white-variables` | 删除：一次性对比截图，内容与新的 01/03/04 重复，且无任何文档引用 |
| `05-settings.png` | 删除并写入 `.gitignore`：该截图会显示本机 `config.json` 的绝对路径（`C:\Users\lihao\Desktop\...`），不适合公开。脚本仍可正常生成，只是不入库 |
| `11-responsive-340/440/600/1000.png` | 保留：白色主题、无隐私内容，README 引用其中两张 |
| `01`～`04`、`06` | 保留：已重新生成为当前白色主题 |

### 2.4 清理

已删除（均为可重建产物，删除前已核对内容）：

- `build/`（约 513 MB，PyInstaller 中间产物与历史 spec 输出）
- `backups/`（约 5.1 MB，两个开发过程快照。已确认其中的 `config.json` 只有空收藏列表与示例 Prompt 的最近记录，`prompts/` 内容与当前目录完全一致，exe 可重新打包）
- 各处 `__pycache__/`、`.pytest_cache/`

**保留未删**（两项与常规「清理开发垃圾」清单不同，理由如下）：

- `dist/`（146 MB）：这是用户日常直接运行的 `AgentDeck.exe` 所在目录，删除后需要重新执行 `build.bat` 才能恢复。它已通过 `.gitignore` 排除，不影响开源目标，因此选择保留而不是删除。
- `.venv/`：删除后无法继续运行测试与开发，同样已被 `.gitignore` 排除。

两者都只存在于本机，不进入 Git。

---

## 3. Privacy（隐私扫描）

扫描范围严格限定为 **`git ls-files` 实际列出的 54 个文件**（即真正准备公开的内容），
未扫描 `.gitignore` 排除的构建目录与虚拟环境。

扫描项与结果：

| 检查项 | 结果 |
| --- | --- |
| Windows 绝对路径（`C:\Users\...`、`Desktop\`） | 未发现 |
| macOS 绝对路径（`/Users/`） | 未发现 |
| 本机用户名（`lihao`） | 未发现 |
| 邮箱地址 | 未发现 |
| `password` / `passwd` / `secret:` | 未发现 |
| `api_key` / `apikey` / GitHub PAT（`ghp_`、`github_pat_`） | 未发现 |
| `Authorization:` / `Bearer` / 私钥块（`BEGIN ... PRIVATE KEY`） | 未发现 |
| 可执行产物（`.exe` / `.dll` / `.pdb`） | 未发现 |
| 单文件 > 5 MB | 未发现（最大文件为 60 KB 的截图） |

另外对全部截图做了人工目视复核（图片内渲染的文字无法用 grep 检出），
确认仅设置界面那张包含本机路径，已按上文处理；其余截图内容为通用示例 Prompt 与界面控件。

`prompts/` 下的 8 个示例 Prompt 均为通用提示词（精读论文、Bug 诊断、Code Review 等），
不含个人内容，随仓库公开。

**结论**：本次受检的 54 个文件中未发现本机路径、凭证或个人信息。
本报告不对「未来任何提交都不含敏感信息」作保证，只陈述上述扫描范围与结果。

---

## 4. Verification（验证记录）

### 4.1 自动化测试

```
$ .venv\Scripts\python.exe -m pytest tests\ -q
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 4.90s
```

88 个用例全部通过。

整理前曾出现 `86 passed, 2 failed`，失败原因是本机正在运行的 `AgentDeck.exe`
（路径已核验为本项目 `dist\AgentDeck\AgentDeck.exe`）占用了 `Alt+Space`，
导致两个全局快捷键用例注册失败。结束该进程后重跑，全部通过——
印证这是环境占用而非代码缺陷，README 中已就此加了说明。

### 4.2 编译校验

```
$ .venv\Scripts\python.exe -m compileall -q main.py src
$ .venv\Scripts\python.exe -m compileall -q tests tools
```

两项均无输出（即无语法错误）。

### 4.3 启动烟雾测试

```
$ .venv\Scripts\python.exe tests\render_screenshots.py
窗口可见：True
窗口取得前台焦点：True
搜索框有焦点：True
扫描到 Prompt：8 个
窗口取得前台焦点：True
全局快捷键已注册：True
托盘可用：True
```

真实启动、真实窗口、无 traceback，验证完毕后正常退出。

```
$ .venv\Scripts\python.exe main.py --check
快捷键可用      : True
托盘可用        : True
Qt 平台         : windows
Python          : 3.10.11
```

环境自检通过，热键在无其他实例运行时可用。

### 4.4 仓库规模

| 指标 | 数值 |
| --- | --- |
| tracked 文件数 | 54 |
| 最大 tracked 文件 | `docs/screenshots/11-responsive-1000.png`（60 KB） |
| 超过 5 MB 的 tracked 文件 | 0 |
| Git 仓库外的源码目录体积 | 约 1 MB（其中截图约 440 KB） |

整理前工作目录为 1.4 GB，整理后为 838 MB（余量全部是已排除的 `.venv` 与 `dist`），
进入 Git 的只有 MB 级源码。

---

## 5. Git

| 项目 | 值 |
| --- | --- |
| 分支 | `main` |
| 首次提交 | `09fe37743c5490636da5299f8ece582edb75588c` |
| 提交信息 | `Initial open-source release` |
| 提交人 | `lihaolun201003 <lihaolun201003@gmail.com>` |
| 工作区状态 | 干净（`git status` 无输出） |

被忽略且未提交的目录：`.venv/`、`data/`、`dist/`、`src/__pycache__/`、`src/ui/__pycache__/`。

`AgentDeck.spec` **已提交**：它是 `build.bat` 正式调用的打包配置，
不是自动生成的临时文件，因此未加入 `.gitignore`。

---

## 6. GitHub

| 项目 | 值 |
| --- | --- |
| 仓库 | [`lihaolun201003/AgentDeck`](https://github.com/lihaolun201003/AgentDeck) |
| 可见性 | **PUBLIC**（`gh repo view --json visibility` 返回 `PUBLIC`） |
| 认证账号 | `lihaolun201003`（token scopes：`gist`、`read:org`、`repo`） |
| remote | `origin` → `https://github.com/lihaolun201003/AgentDeck.git` |
| 默认分支 | `main` |
| push | 成功，`main` 已跟踪 `origin/main` |
| 推送的提交 | `09fe37743c5490636da5299f8ece582edb75588c` |
| 一致性校验 | 本地 `git rev-parse HEAD` 与远端 `git ls-remote origin refs/heads/main` 返回同一个 hash |
| 仓库描述 | 常驻后台的 Windows Prompt 启动器：全局热键呼出、搜索、回车复制到剪贴板 |
| Release | 本轮未创建（项目尚无正式版本号体系，按计划不擅自打 tag） |

创建仓库使用的命令（先用 `gh repo view` 确认同名仓库不存在后再创建，
未对任何已有仓库做覆盖或 force push）：

```bash
gh repo view lihaolun201003/AgentDeck        # 返回 Could not resolve，确认不存在
gh repo create AgentDeck --public --source . --remote origin --description "..."
git push -u origin main
```

`dist/` 及打包后的 exe 未进入 Git 历史，后续如需分发 Windows 可执行版，
建议通过 GitHub Releases 上传 zip 附件。

### 关于本报告

本报告在源码推送成功之后才创建，因此它是仓库的**第二个提交**，
不在上面的首次提交 `09fe377` 之内。
