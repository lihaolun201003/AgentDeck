# Third-Party Notices / 第三方组件说明

AgentDeck 自身以 **MIT License** 发布，见 [LICENSE](LICENSE)。

AgentDeck 依赖或使用了下列第三方组件。这些组件**不是** AgentDeck 的一部分，
它们各自适用其自己的许可条款；本文件仅作说明，不构成法律意见，
也不能替代各组件官方许可文本。

| 组件 | 用途 | 协议（以官方为准） |
| --- | --- | --- |
| [PySide6 (Qt for Python)](https://www.qt.io/qt-for-python) | Python 绑定，界面层 | LGPLv3 / GPLv3 / 商业许可（三重许可） |
| [Qt](https://www.qt.io/) | 底层 C++ 框架 | LGPLv3 / GPLv3 / 商业许可 |
| [PyInstaller](https://pyinstaller.org/) | 打包为 Windows 可执行文件（仅开发/构建期用到） | GPL-2.0-or-later，带允许打包分发应用的例外条款 |

## 对使用者和分发者的提示

- 通过 `pip` 安装依赖时，你获得的是上述组件的官方发行版，请遵守其各自许可。
- 如果你分发 **打包后的 Windows 可执行文件**（`build.bat` 的产物），
  该产物中会包含 Qt / PySide6 的动态链接库。此时请自行确认并遵守
  Qt 与 PySide6 的许可要求（例如 LGPL 对许可声明、可替换库等方面的要求），
  以及 PyInstaller 的许可条款。
- 本文档不给出"是否已完全满足某许可全部要求"的结论，
  请以各组件官方许可文本为准，必要时咨询专业人士。

## 关于 PyInstaller 例外条款

PyInstaller 的许可包含一项例外，明确允许使用它打包并分发**任意许可**的应用
（即打包产物不会因此被要求以 GPL 发布）。该例外仅覆盖 PyInstaller 自身的
bootloader 部分，不影响你仍需遵守 Qt / PySide6 等运行期依赖的许可。
