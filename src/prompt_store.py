"""Prompt 仓库：以 prompts/<分类>/<名称>.md 的形式管理 Markdown 文件。

设计约定：
* 目录名就是 Category，文件名（去掉 .md）就是 Prompt 名称，正文就是要复制的内容。
* 不使用数据库，不使用 YAML front-matter，收藏/最近使用由 :mod:`src.settings` 负责。
* 所有写入都是原子的，写失败不会破坏已有文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .fsutil import atomic_write_text, detect_newline, read_text
from .paths import PROMPTS_DIR
from .variable_parser import extract_variables

#: 没有归属于任何子目录的 Prompt 使用的分类名。
DEFAULT_CATEGORY = "General"

MARKDOWN_SUFFIX = ".md"

#: Windows 文件名非法字符。
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

#: Windows 保留设备名，不能作为文件名。
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

MAX_SEGMENT_LENGTH = 80


class PromptStoreError(Exception):
    """Prompt 仓库操作失败。"""


class InvalidNameError(PromptStoreError):
    """名称无法转换成一个合法的文件名。"""


class PromptExistsError(PromptStoreError):
    """目标文件已存在。"""


@dataclass(frozen=True)
class Prompt:
    """一个 Prompt。``id`` 是相对 prompts/ 的 POSIX 路径，用作收藏/最近使用的键。"""

    id: str
    path: Path
    name: str
    category: str
    content: str
    variables: tuple[str, ...] = ()

    @property
    def has_variables(self) -> bool:
        return bool(self.variables)

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def display_name(self) -> str:
        return f"{self.category} / {self.name}" if self.category else self.name


# ----------------------------------------------------------------------
# 名称清洗
# ----------------------------------------------------------------------
def sanitize_segment(raw: str, fallback: str = "Untitled") -> str:
    """把任意用户输入转换成单个合法的 Windows 路径片段。"""
    text = (raw or "").strip()
    # 去掉控制字符
    text = "".join(ch for ch in text if ord(ch) >= 32)
    # 替换非法字符
    text = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in text)
    # Windows 不允许文件名以空格或点结尾
    text = text.rstrip(" .")
    if not text:
        text = fallback
    if text.upper() in RESERVED_NAMES or text.split(".")[0].upper() in RESERVED_NAMES:
        text = f"_{text}"
    if len(text) > MAX_SEGMENT_LENGTH:
        text = text[:MAX_SEGMENT_LENGTH].rstrip(" .")
    return text or fallback


def sanitize_category(raw: str) -> str:
    """清洗分类名，支持 ``Research/Sub`` 这样的多级分类。"""
    text = (raw or "").strip().strip("/\\")
    if not text:
        return DEFAULT_CATEGORY
    parts = [
        sanitize_segment(part, fallback="Category")
        for part in text.replace("\\", "/").split("/")
        if part.strip()
    ]
    return "/".join(parts) if parts else DEFAULT_CATEGORY


def sanitize_name(raw: str) -> str:
    """清洗 Prompt 名称。"""
    return sanitize_segment(raw, fallback="Untitled")


def _slug_key(segment: str) -> str:
    """用于大小写不敏感比较的键。"""
    return segment.casefold()


# ----------------------------------------------------------------------
# 搜索
# ----------------------------------------------------------------------
def match_score(prompt: Prompt, query: str) -> int:
    """计算匹配得分，0 表示不匹配。

    查询按空白拆成多个关键词，全部命中才算匹配（AND 语义）。
    命中位置权重：名称精确 > 名称前缀 > 名称包含 > 分类 > 正文。
    """
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return 1

    name = prompt.name.lower()
    category = prompt.category.lower()
    content = prompt.content.lower()

    total = 0
    for term in terms:
        if name == term:
            score = 1000
        elif name.startswith(term):
            score = 600
        elif term in name:
            score = 400
        elif term in category:
            score = 200
        elif term in content:
            score = 100
        else:
            return 0
        total += score
    return total


def search_prompts(prompts: list[Prompt], query: str) -> list[Prompt]:
    """返回按相关度排序的匹配结果。"""
    if not query.strip():
        return list(prompts)
    scored: list[tuple[int, str, Prompt]] = []
    for prompt in prompts:
        score = match_score(prompt, query)
        if score > 0:
            scored.append((-score, prompt.display_name, prompt))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored]


# ----------------------------------------------------------------------
# 仓库
# ----------------------------------------------------------------------
class PromptStore:
    """负责 prompts/ 目录的扫描与文件级 CRUD。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else PROMPTS_DIR
        self.errors: list[str] = []

    # ------------------------------------------------------------------
    def scan(self) -> list[Prompt]:
        """扫描目录下所有 Markdown 文件。"""
        self.errors = []
        prompts: list[Prompt] = []
        root = self.root
        if not root.is_dir():
            return prompts

        for path in sorted(root.rglob(f"*{MARKDOWN_SUFFIX}")):
            if not path.is_file() or _is_hidden(root, path):
                continue
            prompt = self._load(path)
            if prompt is not None:
                prompts.append(prompt)

        return self._sorted(prompts)

    def _sorted(self, prompts: list[Prompt]) -> list[Prompt]:
        return sorted(prompts, key=lambda item: (item.category.casefold(), item.name.casefold()))

    def _load(self, path: Path, name: str | None = None, category: str | None = None) -> Prompt | None:
        """读取单个文件；读取失败时记录错误并返回 None。"""
        try:
            content = _read_text_with_fallback(path)
        except OSError as exc:
            self.errors.append(f"{path.name}: 无法读取（{exc.strerror or exc}）")
            return None

        relative = path.relative_to(self.root)
        if category is None:
            category = relative.parent.as_posix()
            if category == ".":
                category = DEFAULT_CATEGORY
        if name is None:
            name = path.stem

        return Prompt(
            id=relative.as_posix(),
            path=path,
            name=name,
            category=category,
            content=content,
            variables=tuple(extract_variables(content)),
        )

    # ------------------------------------------------------------------
    def path_for(self, category: str, name: str) -> Path:
        """按分类与名称推导出目标文件路径。"""
        safe_category = sanitize_category(category)
        safe_name = sanitize_name(name)
        return self.root / Path(safe_category) / f"{safe_name}{MARKDOWN_SUFFIX}"

    def by_id(self, prompt_id: str) -> Prompt | None:
        """按 id 读取单个 Prompt，不存在返回 None。"""
        candidate = (self.root / Path(prompt_id)).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return self._load(candidate)

    # ------------------------------------------------------------------
    def create(self, name: str, category: str, content: str = "") -> Prompt:
        """新建 Prompt 文件，同名文件已存在时抛 :class:`PromptExistsError`。"""
        safe_name = sanitize_name(name)
        safe_category = sanitize_category(category)
        target = self.root / Path(safe_category) / f"{safe_name}{MARKDOWN_SUFFIX}"

        if _exists_case_insensitive(target):
            raise PromptExistsError(f"已存在同名 Prompt：{safe_category} / {safe_name}")

        atomic_write_text(target, content, newline="\n")
        prompt = self._load(target, safe_name, safe_category)
        if prompt is None:
            raise PromptStoreError(f"新建成功但无法读回文件：{target}")
        return prompt

    def update(
        self,
        prompt: Prompt,
        *,
        name: str | None = None,
        category: str | None = None,
        content: str | None = None,
    ) -> Prompt:
        """编辑内容 / 重命名 / 移动分类，并返回更新后的 Prompt。"""
        safe_name = sanitize_name(name) if name is not None else prompt.name
        # 没有显式改分类时保持文件原目录不动（例如用户手工放在 prompts/ 根下的文件）。
        new_category = sanitize_category(category) if category is not None else prompt.category
        new_content = content if content is not None else prompt.content
        newline = detect_newline(prompt.content)

        safe_category = new_category
        if new_category == prompt.category or category is None:
            target = prompt.path.with_name(f"{safe_name}{MARKDOWN_SUFFIX}")
        else:
            target = self.root / Path(safe_category) / f"{safe_name}{MARKDOWN_SUFFIX}"

        same_location = target == prompt.path or _slug_key(str(target)) == _slug_key(str(prompt.path))

        if same_location:
            if target != prompt.path:
                # 仅大小写变化的重命名，Windows 需要真正 rename 才会改变文件名。
                try:
                    prompt.path.rename(target)
                except OSError:
                    target = prompt.path
            atomic_write_text(target, new_content, newline=newline)
            return self._require(target, safe_name, safe_category)

        if _exists_case_insensitive(target):
            raise PromptExistsError(f"已存在同名 Prompt：{safe_category} / {safe_name}")

        target.parent.mkdir(parents=True, exist_ok=True)
        # 先写新文件，再删旧文件：中途失败最多留下副本，不会丢内容。
        atomic_write_text(target, new_content, newline=newline)
        try:
            prompt.path.unlink(missing_ok=True)
        except OSError:
            pass
        _prune_empty_dirs(prompt.path.parent, self.root)
        return self._require(target, safe_name, safe_category)

    def save_content(self, prompt: Prompt, content: str) -> Prompt:
        """只更新正文，保持文件原有换行风格。"""
        newline = detect_newline(prompt.content)
        atomic_write_text(prompt.path, content, newline=newline)
        return self._require(prompt.path, prompt.name, prompt.category)

    def delete(self, prompt: Prompt) -> None:
        """删除 Prompt 文件，并清理因此变空的目录。"""
        try:
            prompt.path.unlink()
        except FileNotFoundError:
            return
        _prune_empty_dirs(prompt.path.parent, self.root)

    def _require(self, path: Path, name: str, category: str) -> Prompt:
        prompt = self._load(path, name, category)
        if prompt is None:
            raise PromptStoreError(f"无法读取文件：{path}")
        return prompt

    # ------------------------------------------------------------------
    def categories(self) -> list[str]:
        """返回磁盘上存在的所有分类（含空目录）。"""
        names: set[str] = set()
        if not self.root.is_dir():
            return []
        for path in self.root.rglob("*"):
            if not path.is_dir() or _is_hidden(self.root, path):
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative:
                names.add(relative)
        return sorted(names, key=str.casefold)

    def create_category(self, name: str) -> str:
        """新建分类目录（已存在则直接复用），返回清洗后的分类名。"""
        safe_category = sanitize_category(name)
        (self.root / Path(safe_category)).mkdir(parents=True, exist_ok=True)
        return safe_category

    def is_empty(self) -> bool:
        """prompts/ 下是否一个 Markdown 文件都没有。"""
        if not self.root.is_dir():
            return True
        return next(self.root.rglob(f"*{MARKDOWN_SUFFIX}"), None) is None


# ----------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------
def _read_text_with_fallback(path: Path) -> str:
    """按 UTF-8 读取，失败时回退 GBK，最后用替换字符兜底。"""
    try:
        return read_text(path)
    except UnicodeDecodeError:
        pass
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _is_hidden(root: Path, path: Path) -> bool:
    """跳过隐藏目录与 Office 产生的临时文件。"""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part.startswith(".") for part in relative.parts):
        return True
    return path.name.startswith("~$")


def _exists_case_insensitive(path: Path) -> bool:
    """Windows 文件系统不区分大小写，判重时统一按小写比较。"""
    if path.exists():
        return True
    parent = path.parent
    if not parent.is_dir():
        return False
    target = _slug_key(path.name)
    try:
        return any(_slug_key(child.name) == target for child in parent.iterdir())
    except OSError:
        return False


def _prune_empty_dirs(directory: Path, stop_at: Path) -> None:
    """自底向上删除空目录，遇到 stop_at 或非空目录即停止。"""
    current = directory
    stop = stop_at.resolve()
    while True:
        try:
            if current.resolve() == stop:
                return
            if not current.is_dir():
                return
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


__all__ = [
    "DEFAULT_CATEGORY",
    "InvalidNameError",
    "Prompt",
    "PromptExistsError",
    "PromptStore",
    "PromptStoreError",
    "match_score",
    "sanitize_category",
    "sanitize_name",
    "sanitize_segment",
    "search_prompts",
]
