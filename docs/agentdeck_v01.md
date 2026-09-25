# AgentDeck v0.1 开发说明

本文档记录第一版的实现细节、关键决策和已知限制，面向后续维护者（包括未来的自己）。

---

## 1. 目标与设计取舍

**定位**：常驻后台的 Prompt 启动器。核心链路只有一条 ——
`全局热键 → 弹窗 → 搜索 → 选择 → 回车 → 剪贴板 → 自动隐藏`。

围绕这条链路做的取舍：

| 决策 | 原因 |
| --- | --- |
| 用 Markdown 文件而不是数据库 | 用户可以直接用编辑器批量管理，删除目录即卸载数据，不用提供导入导出 |
| 用 `ctypes + RegisterHotKey` 而不是 `keyboard` / `pynput` | 不引入第三方依赖；`keyboard` 需要管理员权限，`pynput` 是全局钩子，代价都更高 |
| 不写 YAML front-matter | 需求明确要求"不要复杂 metadata"，收藏/最近使用放在 `config.json` |
| 原生标题栏 | 需要 Windows 贴靠分屏与系统最大化菜单；自己实现的无边框窗口拿不到这些系统能力 |
| 每次呼出窗口都重新扫描 `prompts/` | 扫描 8~200 个 Markdown 只需几毫秒，换来"新增文件立刻可见" |
| 单实例互斥 | 否则第二个实例必然注册不上热键，用户会困惑 |

---

## 2. 目录结构与职责

```
AgentDeck/
├── main.py                    入口：修好 sys.path 后调用 src.app.main
├── build.bat                  PyInstaller 打包（纯 ASCII，见"打包"一节）
├── requirements.txt           运行依赖：仅 PySide6
├── requirements-dev.txt       开发依赖：pytest + pyinstaller
├── LICENSE                    MIT
├── THIRD_PARTY_NOTICES.md     第三方组件许可说明
├── prompts/                   Prompt 数据（分类目录 + .md）
├── data/config.json           收藏 / 最近使用 / 窗口 / 快捷键（本地运行数据，不入库）
├── assets/agentdeck.ico       打包时生成
├── tools/make_icon.py         由 src.app.build_app_icon 生成 .ico
├── src/
│   ├── paths.py               路径解析：开发模式 vs 打包模式
│   ├── fsutil.py              原子写入、换行风格保持
│   ├── settings.py            config.json 的读写与字段校验
│   ├── prompt_store.py        扫描、搜索、增删改查、文件名清洗
│   ├── variable_parser.py     {{VARIABLE}} 提取与替换
│   ├── clipboard.py           剪贴板读写 + 读回校验
│   ├── hotkey.py              RegisterHotKey 线程、前台窗口激活
│   ├── seeds.py               首次运行的示例 Prompt
│   ├── app.py                 应用装配：托盘、热键、生命周期、自检
│   └── ui/
│       ├── theme.py           白色调色板 + QSS + 全局界面字号
│       ├── widgets.py         搜索框与两个列表委托
│       ├── main_window.py     主窗口与全部交互
│       ├── prompt_editor.py   新建 / 编辑 / 重命名对话框
│       ├── variable_dialog.py 变量填写对话框
│       └── settings_dialog.py 设置对话框（含快捷键录制控件）
├── tests/
│   ├── test_core.py           核心模块（无 GUI）
│   ├── test_gui.py            offscreen 下的界面与热键测试
│   ├── e2e_journey.py         真实窗口 + 真实按键的端到端验证
│   └── render_screenshots.py  真实启动并抓图，输出到 docs/screenshots/
└── docs/agentdeck_v01.md      本文件（另有 responsive-window.md 等专题说明）
```

依赖方向是单向的：`ui/* → prompt_store / settings / variable_parser / hotkey → fsutil / paths`。
`ui` 层不直接读写文件；`store` / `settings` 层不导入 PySide6（`clipboard.py` 例外，它本身就是一个 Qt 封装）。

---

## 3. 数据格式

### 3.1 Prompt

```
prompts/<分类>/<名称>.md
```

* 分类 = 相对 `prompts/` 的目录路径，支持多级（`Research/2024`）
* 名称 = 文件名去掉 `.md`
* 正文 = 文件全部内容，复制时逐字节输出（不做 Markdown 渲染、不加任何包装）
* `prompts/` 根目录下的 `.md` 会被归到 `General` 分类，重命名时也保持在原目录
* 名称以 `.` 开头的文件、`~$` 开头的 Office 临时文件不会被扫描

Prompt 在程序内的唯一标识 `Prompt.id` 是**相对 `prompts/` 的 POSIX 路径**，例如
`Research/精读论文.md`。收藏和最近使用都存这个字符串，所以把整个 `prompts/`
目录搬到别的盘符也不会失效；但手工在资源管理器里改名会让收藏记录失效
（程序启动时会自动清理掉这些悬空记录）。

### 3.2 config.json

```json
{
  "hotkey": "Alt+Space",
  "always_on_top": true,
  "hide_after_copy": true,
  "favorites": ["Coding/Bug诊断.md"],
  "recent": ["Coding/Bug诊断.md", "Research/精读论文.md"],
  "window_width": 820,
  "window_height": 520,
  "schema_version": 1
}
```

读取时的容错策略（`Settings._apply`）：

* 文件不存在 → 用默认值
* JSON 语法错误 / 不是对象 → 改名成 `config.json.bak` 保留现场，然后用默认值
* 单个字段类型不对 → 该字段用默认值，其余字段照常生效
* 数值字段会被夹到合理区间（窗口宽度 640–1920）

写入始终是原子的：先写同目录临时文件 → `fsync` → `os.replace`。

---

## 4. 关键实现说明

### 4.1 全局快捷键（`src/hotkey.py`）

`RegisterHotKey` 注册的热键，`WM_HOTKEY` 只会投递到**注册它的那个线程**的消息队列。
因此 `HotkeyListener(QThread)` 在自己的 `run()` 里做三件事：

1. 调 `PeekMessageW` 强制创建线程消息队列（`RegisterHotKey` 的前置条件）；
2. `RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, vk)`；`MOD_NOREPEAT`
   避免按住不放时连续触发；
3. 跑 `GetMessageW` 循环，收到 `WM_HOTKEY` 就 `emit activated`（跨线程自动走队列连接）。

线程退出：`stop()` 调 `PostThreadMessageW(thread_id, WM_QUIT, 0, 0)`，
`GetMessageW` 返回 0 后跳出循环，`finally` 里 `UnregisterHotKey`，线程自然结束。

几个容易踩的点，代码里都已经处理：

* `GetMessageW` 的 `restype` 必须是 `c_int`：它出错时返回 `-1`，
  如果用 `wintypes.BOOL` 会被截断成 `1`，循环就永远退不出来。
* 注册失败时不能用 `ctypes.get_last_error()` 直接读，必须用
  `ctypes.WinDLL("user32", use_last_error=True)` 创建句柄，否则拿到的错误码是脏的。
* 错误码 1409（`ERROR_HOTKEY_ALREADY_REGISTERED`）会被翻译成
  "该快捷键已被其他程序占用"，通过 `registration_failed` 信号送回主线程，
  由状态栏 + 托盘气泡提示，**不会崩溃也不会静默失败**。

`probe_hotkey()` 用于设置界面：在调用线程里试注册一次再立刻注销，用来判断某个
组合是否可用。注意如果被测组合正是程序**当前正在使用**的那个，探测一定失败
（自己占着），所以设置界面里与当前值相同的快捷键会跳过探测。

### 4.2 呼出时抢前台焦点（`force_foreground`）

Windows 禁止后台进程随意抢占前台窗口，`SetForegroundWindow` 经常只让任务栏图标闪烁。
这里用了经典的 `AttachThreadInput` 手法：

```python
foreground = GetForegroundWindow()
target_thread = GetWindowThreadProcessId(foreground, None)
AttachThreadInput(target_thread, current_thread, True)   # 临时把两条线程的输入队列合并
BringWindowToTop(hwnd)
SetForegroundWindow(hwnd)
AttachThreadInput(target_thread, current_thread, False)  # 立刻解除
```

调用时机很关键：必须等 Qt 的 `show()` 真正创建了原生窗口之后再调，
所以 `show_launcher()` 里用 `QTimer.singleShot(0, self._grab_foreground)` 把这一步
推迟到事件循环的下一次迭代。失败也不抛异常，Qt 自己的
`raise_()` + `activateWindow()` 还会兜底。

实测（`tests/e2e_journey.py`）在 Windows 11 上呼出后 `isActiveWindow()` 为 `True`，
可以直接开始打字。

### 4.3 无边框窗口

`MainWindow` 用 `Qt.Window | Qt.FramelessWindowHint`，因此需要自己补三件事：

* **拖动**：顶部 30px 的 `DragBar` 记录按下时的偏移量，在 `mouseMove` 里 `move()`。
* **缩放**：右下角放一个 `QSizeGrip`。
* **关闭**：`closeEvent` 里 `event.ignore()` 后只做隐藏 —— 与需求一致，
  真正退出只能走托盘菜单，避免用户"点叉号以为退出、其实进程还在"。

`Always on Top` 通过 `setWindowFlag(Qt.WindowStaysOnTopHint, ...)` 动态切换。
注意 Qt 改窗口 flag 会导致原生窗口重建，所以 `_apply_topmost_flag()` 里判断
当前是否可见，可见就补一次 `show()`。

### 4.4 窗口隐藏后仍在后台

`QApplication.setQuitOnLastWindowClosed(False)` 是这条需求的关键。
配合托盘图标（`QSystemTrayIcon`）保证用户始终有退出入口。

### 4.5 文件写入安全（`src/fsutil.py`）

Prompt 是用户的真实数据，因此：

* **原子写入**：临时文件 → `fsync` → `os.replace`，同一目录保证同卷原子性；
  写失败时删除临时文件，原文件不动。
* **换行保持**：读取用 `newline=""` 不做任何转换，复制出去的内容与磁盘逐字节一致；
  保存时用 `detect_newline()` 判断原文件是 CRLF 还是 LF，按原风格写回。
* **重命名安全**：先写新文件、再删旧文件，中途失败最坏是留下一份副本，不会丢内容。

### 4.6 文件名清洗

`sanitize_segment()` 依次处理：去控制字符 → 替换 `< > : " / \ | ? *` 为 `_` →
去掉结尾的空格和点 → 检查 Windows 保留名（`CON`、`PRN`、`COM1`…，冲突时加前缀 `_`）→
截断到 80 字符。分类名按 `/` 拆段分别清洗，所以 `研究/2024` 这种多级分类是安全的。

编辑器会在输入时实时提示"名称含非法字符，将保存为 XXX"，用户不会在保存后才发现名字变了。

### 4.7 搜索与排序（`prompt_store.match_score`）

查询按空白拆词，**全部命中才算匹配**（AND 语义），单个词按命中位置打分：

```
名称精确 1000 > 名称前缀 600 > 名称包含 400 > 分类包含 200 > 正文包含 100
```

总分降序、同分按 `分类/名称` 升序。中文不需要分词，直接子串匹配即可
（"论文" 能命中 "精读论文"）。

### 4.8 变量解析（`src/variable_parser.py`）

正则 `\{\{([^{}\r\n]{1,64}?)\}\}`：

* 变量名允许中文、字母、数字、下划线，两侧空白自动忽略（`{{ TASK }}` 与 `{{TASK}}` 等价）
* 提取时按首次出现顺序去重（`extract_variables`）
* 替换时同名变量全部替换；**未提供取值的变量保持原样**，避免漏填时静默丢信息
* 代码块里的 `${{ github.ref }}` 这类写法也会被识别为变量 —— 这是"任何
  `{{NAME}}` 都自动识别"这条需求的直接结果，属于已知取舍

填写窗口里若某个变量留空，第一次点「复制」只会给出提示，再点一次才真正复制，
防止误触。

### 4.9 列表绘制（`src/ui/widgets.py`）

结果列表每项 44px，两行：上行是 Prompt 名称（可省略号截断），下行是分类路径，
右侧在有变量时显示 `{{ }} 变量` 徽章。侧边栏每项 26px，左侧名称、右侧数量。
两个 `QStyledItemDelegate` 自己画选中背景（圆角 + 左侧 2px 强调条），
QSS 里把 `QListWidget::item:selected` 的背景设成透明，避免和委托重复绘制。

### 4.10 样式表的两处"不改"

`QComboBox` 和 `QCheckBox` 没有写进 QSS。一旦用 QSS 覆盖这两个控件的边框，
Qt 就不再绘制下拉箭头和勾选标记（需要自己提供图片资源）。这里让
Fusion 风格 + 浅色 `QPalette` 负责它们的外观，视觉上一致且不会丢控件元素。

---

## 5. 运行时行为

### 启动

1. 单实例互斥（命名互斥体 `Local\AgentDeck.SingleInstance`），已有实例则弹提示后退出
2. 创建 `QApplication` → Fusion 风格 + 浅色调色板 + QSS → 加载 Qt 中文翻译
3. 读取 `data/config.json`；`prompts/` 为空时写入 8 个示例 Prompt
4. 构建主窗口、托盘、注册全局快捷键，最后 `show_launcher()` 显示窗口

### 呼出（热键 / 托盘菜单 / 双击托盘图标）

`show_launcher()` 依次做：同步置顶 flag → 清空搜索框（屏蔽信号）→
把分类重置回「全部」→ 重新扫描 `prompts/` → 选中第 1 项 →
移动到鼠标所在屏幕的居中偏上位置 → `show + raise + activateWindow` →
搜索框聚焦 → 下一轮事件循环里 `force_foreground`。

热键的行为是**切换**：窗口已经在前台时按热键会隐藏（`_toggle_window`）。

### 复制

无变量 → 直接写剪贴板；有变量 → 弹填写框 → `substitute()` →
写剪贴板（写后读回校验）→ 记录 Recent → 状态栏显示 `Copied ✓` →
若开启 `hide_after_copy` 则在 420ms 后隐藏。

隐藏前会把窗口尺寸写回 `config.json`（仅在尺寸变化时落盘）。

### 退出

只走托盘菜单「退出」：保存窗口尺寸与配置 → 停止热键线程 → 隐藏托盘 → `app.quit()`。
`aboutToQuit` 上还挂了一次 `_shutdown()` 作为兜底。

---

## 6. 测试

```bat
rem 完整自动化测试套件
.venv\Scripts\python.exe -m pytest tests\ -q

rem 真实窗口 + 真实按键的端到端验证（会短暂显示窗口）
.venv\Scripts\python.exe tests\e2e_journey.py

rem 抓取界面截图到 docs/screenshots/
.venv\Scripts\python.exe tests\render_screenshots.py

rem 环境自检（打包后也能用）
.venv\Scripts\python.exe main.py --check
```

覆盖情况：

| 需求 | 验证方式 |
| --- | --- |
| Prompt 扫描 | `test_scan_*`（含隐藏目录、Office 临时文件、正文保真） |
| 中文路径 / 文件名 | `test_chinese_path_roundtrip`、`test_sanitize_*` |
| 搜索 | `test_search_*`（名称/分类/正文、大小写、多词 AND、排序） |
| 收藏持久化 | `test_favorites_and_recent_persist`、损坏配置与类型错误容错 |
| Recent | `test_recent_is_deduped_and_capped`、界面侧 `test_recent_updates_after_copy` |
| 编辑保存 | `test_update_content_keeps_crlf`（CRLF 保持）、`test_write_is_atomic_*` |
| 新建 / 重命名 / 删除 | `test_rename_prompt_moves_file`、`test_create_duplicate_raises`、界面侧用例 |
| `{{VARIABLE}}` | `test_extract_variables_*`、`test_substitute_*`、`test_enter_on_variable_prompt_substitutes` |
| 剪贴板 | `test_clipboard_*` |
| Alt+Space 全局快捷键 | `test_global_hotkey_registers_and_fires`（真实注册 + `keybd_event` 模拟按键） |
| Esc 隐藏 | `test_escape_hides_window`、`test_escape_shortcut_is_bound` |
| Enter 复制 | `test_enter_copies_selected_prompt` |
| 隐藏后再次呼出 | `test_hotkey_recalls_window_after_hiding`、`e2e_journey.py` 第 15–16 项 |

注意事项：

* 全局热键测试会真实注册 `Alt+Space`，**运行测试前请先退出正在运行的 AgentDeck**，
  否则会被判定为"已被占用"而失败。
* GUI 测试默认用 `QT_QPA_PLATFORM=offscreen`，不会弹窗；`e2e_journey.py` 和
  `render_screenshots.py` 会真实显示窗口。

---

## 7. 打包

```bat
build.bat
```

产物 `dist\AgentDeck\AgentDeck.exe`（onedir 模式）。

要点：

* `--windowed`：不弹控制台窗口。副作用是 `sys.stdout` 变成 `None`，
  所以程序里所有 `print` 都必须能容忍失败（`run_self_check` 里用 `try` 包住，
  并把结果同时写到 `data/selfcheck.txt`）。
* **不打包 `prompts/` 和 `data/`**：`src/paths.py` 在 frozen 模式下把
  `sys.executable` 的父目录当作数据根目录，也就是"exe 旁边"。
  如果这两个目录被塞进 `_MEIPASS`（只读临时目录），用户的修改就会丢。
  `build.bat` 改为在打包结束后把示例 `prompts/` 复制到 `dist\AgentDeck\`。
* `build.bat` 必须是**纯 ASCII**：cmd.exe 在 UTF-8 与 936 代码页之间解析中文会
  截断命令行，导致脚本报出一堆"'xxx' 不是内部或外部命令"。
* 打包后自检：`dist\AgentDeck\AgentDeck.exe --check`，
  几秒后看 `dist\AgentDeck\data\selfcheck.txt`。

---

## 8. 已知限制

1. **只支持 Windows**。全局快捷键走的是 Win32 `RegisterHotKey`；
   `parse_hotkey` / `probe_hotkey` 在其它平台上会返回"仅支持 Windows"而不崩溃，
   但热键功能不可用。
2. **`Alt+Space` 会占用系统窗口菜单**。这是默认值带来的必然结果，README 里
   已在常见问题中说明，可在设置里改。
3. **变量填写框是单行输入**。`TASK` 这类需要多行的变量只能写成一行。
4. **不支持搜索拼音首字母**（输入 `jdlw` 找不到"精读论文"），只做子串匹配。
5. **收藏记录依赖文件路径**。在资源管理器里手工改名后收藏会失效，
   启动时会自动清理这些悬空记录（会有一次静默的 `config.json` 写入）。
6. **托盘不可用时没有退出入口**。此时程序会打印一行警告，
   只能从任务管理器结束进程（Windows 上正常环境不会出现）。
7. **`prompts/` 根目录下的文件**分类显示为 `General`，但文件实际仍在根目录，
   只有显式改成别的分类才会移动 —— 这是为了避免手工摆放的文件被程序悄悄挪走。

---

## 9. 后续可以做的事

按性价比排序，都不是第一版必须的：

1. 呼出窗口时把上一次选中的 Prompt 也考虑进排序（"上次复制过"加权）
2. 变量填写支持多行与历史值记忆
3. 拼音/首字母搜索
4. 可切换的深色配色（当前只有一套白色主题；界面字号已可在设置里调整）
5. `Ctrl+1..9` 快速复制第 N 项
6. 托盘菜单里加「打开 prompts 目录」
