"""核心模块测试：扫描、中文路径、搜索、CRUD、变量、配置持久化。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fsutil import atomic_write_text, detect_newline, read_text  # noqa: E402
from src.prompt_store import (  # noqa: E402
    Prompt,
    PromptExistsError,
    PromptStore,
    match_score,
    sanitize_category,
    sanitize_name,
    search_prompts,
)
from src.settings import (  # noqa: E402
    DEFAULT_FONT_SIZE,
    MAX_FONT_SIZE,
    MAX_RECENT,
    MIN_FONT_SIZE,
    Settings,
)
from src.variable_parser import extract_variables, has_variables, substitute  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> PromptStore:
    """建立一个带中文分类与中文文件名的 Prompt 仓库。"""
    root = tmp_path / "prompts"
    atomic_write_text(root / "Research" / "精读论文.md", "精读本文：研究问题｜核心贡献。\n")
    atomic_write_text(root / "Coding" / "Bug诊断.md", "先复现并定位真实根因，不要立即修改代码。\n")
    atomic_write_text(
        root / "Coding" / "项目诊断.md",
        "请检查以下项目：\n\n{{PROJECT_PATH}}\n\n当前任务：\n\n{{TASK}}\n\n找出真实根因。\n",
    )
    atomic_write_text(root / "Writing" / "技术报告.md", "请把以下内容整理成技术报告。\n")
    return PromptStore(root)


# ----------------------------------------------------------------------
# 1. 扫描
# ----------------------------------------------------------------------
def test_scan_finds_all_markdown(store: PromptStore) -> None:
    prompts = store.scan()
    assert len(prompts) == 4
    names = {prompt.name for prompt in prompts}
    assert names == {"精读论文", "Bug诊断", "项目诊断", "技术报告"}
    categories = {prompt.category for prompt in prompts}
    assert categories == {"Research", "Coding", "Writing"}
    assert store.errors == []


def test_scan_ignores_hidden_and_temp_files(store: PromptStore) -> None:
    hidden_dir = store.root / ".hidden"
    atomic_write_text(hidden_dir / "x.md", "隐藏目录里的内容\n")
    atomic_write_text(store.root / "Writing" / "~$草稿.md", "office 临时文件\n")

    prompts = store.scan()
    assert len(prompts) == 4


def test_scan_returns_content_verbatim(store: PromptStore) -> None:
    prompt = next(p for p in store.scan() if p.name == "项目诊断")
    assert "{{PROJECT_PATH}}" in prompt.content
    assert prompt.variables == ("PROJECT_PATH", "TASK")
    assert prompt.has_variables is True


# ----------------------------------------------------------------------
# 2. 中文路径与文件名
# ----------------------------------------------------------------------
def test_chinese_path_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "中文目录" / "prompts"
    store = PromptStore(root)
    prompt = store.create("需求整理", "产品/中文分类", "把需求整理成清单。\n")

    assert prompt.path.exists()
    assert prompt.path.name == "需求整理.md"
    assert prompt.category == "产品/中文分类"
    assert prompt.content == "把需求整理成清单。\n"

    reread = store.by_id(prompt.id)
    assert reread is not None
    assert reread.content == prompt.content


def test_sanitize_name_strips_invalid_windows_chars() -> None:
    assert sanitize_name('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_name("  结尾点.  ") == "结尾点"
    assert sanitize_name("") == "Untitled"
    assert sanitize_name("CON") == "_CON"
    assert sanitize_name("正常名称") == "正常名称"


def test_sanitize_category_supports_nesting() -> None:
    assert sanitize_category("Research") == "Research"
    assert sanitize_category("A/B") == "A/B"
    assert sanitize_category("") == "General"
    assert sanitize_category("父/子/孙") == "父/子/孙"


def test_create_with_illegal_name_is_sanitized(store: PromptStore) -> None:
    prompt = store.create("非法:名字?", "Research", "内容")
    assert prompt.name == "非法_名字_"
    assert prompt.path.exists()


# ----------------------------------------------------------------------
# 3. 搜索
# ----------------------------------------------------------------------
def test_search_matches_name_category_and_content(store: PromptStore) -> None:
    prompts = store.scan()

    by_name = search_prompts(prompts, "精读")
    assert [p.name for p in by_name] == ["精读论文"]

    by_content = search_prompts(prompts, "根因")
    assert {p.name for p in by_content} == {"Bug诊断", "项目诊断"}

    by_category = search_prompts(prompts, "writing")
    assert {p.name for p in by_category} == {"技术报告"}


def test_search_is_case_insensitive_and_ranks_name_first(store: PromptStore) -> None:
    prompts = store.scan()
    results = search_prompts(prompts, "bug")
    assert results[0].name == "Bug诊断"


def test_search_multi_term_requires_all_terms(store: PromptStore) -> None:
    prompts = store.scan()
    assert [p.name for p in search_prompts(prompts, "项目 根因")] == ["项目诊断"]
    assert search_prompts(prompts, "项目 不存在的词") == []


def test_empty_query_returns_everything(store: PromptStore) -> None:
    prompts = store.scan()
    assert len(search_prompts(prompts, "   ")) == len(prompts)


def test_match_score_zero_for_miss(store: PromptStore) -> None:
    prompt = store.scan()[0]
    assert match_score(prompt, "zzz-不存在") == 0


# ----------------------------------------------------------------------
# 4/5. 收藏与最近使用持久化
# ----------------------------------------------------------------------
def test_favorites_and_recent_persist(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    settings = Settings()
    settings.toggle_favorite("Research/精读论文.md")
    settings.add_recent("Coding/Bug诊断.md")
    settings.save(config)

    reloaded = Settings.load(config)
    assert reloaded.is_favorite("Research/精读论文.md")
    assert reloaded.recent == ["Coding/Bug诊断.md"]


def test_recent_is_deduped_and_capped(tmp_path: Path) -> None:
    settings = Settings()
    for index in range(MAX_RECENT + 8):
        settings.add_recent(f"Cat/p{index}.md")

    assert len(settings.recent) == MAX_RECENT
    assert settings.recent[0] == f"Cat/p{MAX_RECENT + 7}.md"

    settings.add_recent(f"Cat/p{MAX_RECENT}.md")
    assert settings.recent[0] == f"Cat/p{MAX_RECENT}.md"
    assert len(settings.recent) == MAX_RECENT
    assert settings.recent.count(f"Cat/p{MAX_RECENT}.md") == 1


def test_favorite_toggle_returns_new_state() -> None:
    settings = Settings()
    assert settings.toggle_favorite("a.md") is True
    assert settings.is_favorite("a.md") is True
    assert settings.toggle_favorite("a.md") is False
    assert settings.is_favorite("a.md") is False


def test_rename_and_remove_id_migrate_records() -> None:
    settings = Settings()
    settings.toggle_favorite("A/old.md")
    settings.add_recent("A/old.md")

    settings.rename_id("A/old.md", "B/new.md")
    assert settings.favorites == ["B/new.md"]
    assert settings.recent == ["B/new.md"]

    settings.remove_id("B/new.md")
    assert settings.favorites == []
    assert settings.recent == []


def test_settings_survive_corrupted_file(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{ 这不是合法 JSON", encoding="utf-8")

    settings = Settings.load(config)
    assert settings.hotkey == "Alt+Space"
    assert config.with_suffix(".json.bak").exists()


def test_settings_rejects_wrong_types(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"hotkey": 123, "favorites": "not-a-list", "always_on_top": "yes"}),
        encoding="utf-8",
    )
    settings = Settings.load(config)
    assert settings.hotkey == "Alt+Space"
    assert settings.favorites == []
    assert settings.always_on_top is True


def test_window_placement_and_config_location_persist(tmp_path: Path) -> None:
    config = tmp_path / "panel-config.json"
    settings = Settings.load(config)
    settings.window_width = 410
    settings.window_x = -1800
    settings.window_y = 40
    settings.window_maximized = True
    settings.hide_after_copy = False
    settings.save()
    restored = Settings.load(config)
    assert restored.window_width == 410
    assert restored.window_x == -1800
    assert restored.window_y == 40
    assert restored.window_maximized is True
    assert restored.hide_after_copy is False


def test_invalid_placement_values_use_defaults(tmp_path: Path) -> None:
    config = tmp_path / "bad-position.json"
    config.write_text(json.dumps({"window_x": True, "window_y": "50",
                                  "window_maximized": "yes", "window_width": 1}), encoding="utf-8")
    settings = Settings.load(config)
    assert settings.window_x is None
    assert settings.window_y is None
    assert settings.window_maximized is False
    assert settings.window_width == 340


# ----------------------------------------------------------------------
# 界面字号
# ----------------------------------------------------------------------
def test_font_size_defaults_to_14(tmp_path: Path) -> None:
    assert Settings().font_size == DEFAULT_FONT_SIZE == 14

    # 全新的配置文件同样从默认值开始
    config = tmp_path / "fresh.json"
    assert Settings.load(config).font_size == 14


def test_font_size_persists_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    settings = Settings()
    settings.font_size = 18
    settings.save(config)

    assert json.loads(config.read_text(encoding="utf-8"))["font_size"] == 18
    assert Settings.load(config).font_size == 18


def test_legacy_config_without_font_size_loads_default(tmp_path: Path) -> None:
    """旧版 config 没有 font_size：读取不报错，且默认 14。"""
    config = tmp_path / "legacy.json"
    config.write_text(
        json.dumps(
            {
                "hotkey": "Ctrl+Alt+Q",
                "always_on_top": False,
                "hide_after_copy": False,
                "favorites": ["A/b.md"],
                "recent": ["A/b.md"],
                "window_width": 700,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    settings = Settings.load(config)
    assert settings.font_size == DEFAULT_FONT_SIZE
    assert settings.hotkey == "Ctrl+Alt+Q"
    assert settings.always_on_top is False
    assert settings.window_width == 700
    assert not config.with_suffix(".json.bak").exists()  # 没被当成损坏配置

    # 保存后补上新键，老键一个不丢
    settings.save()
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["font_size"] == 14
    assert data["hotkey"] == "Ctrl+Alt+Q"
    assert data["favorites"] == ["A/b.md"]


@pytest.mark.parametrize(
    "stored, expected",
    [(4, MIN_FONT_SIZE), (10, 10), (24, 24), (99, MAX_FONT_SIZE)],
)
def test_font_size_is_clamped_to_range(tmp_path: Path, stored: int, expected: int) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"font_size": stored}), encoding="utf-8")
    assert Settings.load(config).font_size == expected


def test_font_size_rejects_wrong_type(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"font_size": "18"}), encoding="utf-8")
    assert Settings.load(config).font_size == DEFAULT_FONT_SIZE


# ----------------------------------------------------------------------
# 6/7. 编辑保存、新建、重命名、删除
# ----------------------------------------------------------------------
def test_update_content_keeps_crlf(store: PromptStore) -> None:
    path = store.root / "Writing" / "技术报告.md"
    atomic_write_text(path, "第一行\r\n第二行\r\n", newline="\r\n")
    prompt = store.by_id("Writing/技术报告.md")
    assert prompt is not None
    assert detect_newline(prompt.content) == "\r\n"

    updated = store.save_content(prompt, "第一行\n第二行改了\n")
    assert detect_newline(updated.content) == "\r\n"
    assert updated.content == "第一行\r\n第二行改了\r\n"
    assert read_text(path) == "第一行\r\n第二行改了\r\n"


def test_rename_prompt_moves_file(store: PromptStore) -> None:
    prompt = store.by_id("Research/精读论文.md")
    assert prompt is not None
    old_path = prompt.path

    updated = store.update(prompt, name="精读论文v2")
    assert updated.name == "精读论文v2"
    assert updated.id == "Research/精读论文v2.md"
    assert updated.path.exists()
    assert not old_path.exists()
    assert updated.content == prompt.content


def test_change_category_moves_file(store: PromptStore) -> None:
    prompt = store.by_id("Research/精读论文.md")
    assert prompt is not None

    updated = store.update(prompt, category="新手分类")
    assert updated.path == store.root / "新手分类" / "精读论文.md"
    assert updated.path.exists()
    assert not prompt.path.exists()
    # 旧目录里没有其它文件，应该被清理掉
    assert not (store.root / "Research").exists()


def test_create_duplicate_raises(store: PromptStore) -> None:
    with pytest.raises(PromptExistsError):
        store.create("精读论文", "Research", "重复内容")


def test_delete_removes_file_and_empty_dir(store: PromptStore) -> None:
    prompt = store.by_id("Writing/技术报告.md")
    assert prompt is not None
    store.delete(prompt)

    assert not prompt.path.exists()
    assert not (store.root / "Writing").exists()
    assert len(store.scan()) == 3


def test_create_category(store: PromptStore) -> None:
    category = store.create_category("新 分类/子级")
    assert (store.root / "新 分类" / "子级").is_dir()
    assert category == "新 分类/子级"
    assert "新 分类/子级" in store.categories()


def test_write_is_atomic_and_leaves_no_temp_files(store: PromptStore) -> None:
    prompt = store.by_id("Coding/Bug诊断.md")
    assert prompt is not None
    store.save_content(prompt, "新的内容\n")

    leftovers = [p.name for p in prompt.path.parent.iterdir() if p.name.startswith(".agentdeck-")]
    assert leftovers == []


# ----------------------------------------------------------------------
# 8. 变量检测与替换
# ----------------------------------------------------------------------
def test_extract_variables_dedupes_in_order() -> None:
    text = "{{B}} 先出现 {{A}}，然后 {{B}} 再来一次，{{中文变量}} 也可以。"
    assert extract_variables(text) == ["B", "A", "中文变量"]


def test_extract_variables_ignores_non_variables() -> None:
    assert extract_variables("普通文本 { 单括号 } {{}} {{ }}") == []
    assert extract_variables("代码里的 ${{ github.ref }} 不是") == ["github.ref"]


def test_substitute_replaces_all_occurrences() -> None:
    text = "路径：{{P}}\n再说一次：{{P}}\n任务：{{T}}"
    result = substitute(text, {"P": r"C:\项目\demo", "T": "修 bug"})
    assert result == "路径：C:\\项目\\demo\n再说一次：C:\\项目\\demo\n任务：修 bug"
    assert "{{" not in result


def test_substitute_keeps_unknown_variables() -> None:
    text = "{{KNOWN}} 和 {{UNKNOWN}}"
    assert substitute(text, {"KNOWN": "值"}) == "值 和 {{UNKNOWN}}"


def test_has_variables() -> None:
    assert has_variables("{{A}}") is True
    assert has_variables("没有变量") is False


def test_substitution_does_not_touch_prompt_file(store: PromptStore) -> None:
    prompt = store.by_id("Coding/项目诊断.md")
    assert prompt is not None
    before = prompt.path.read_bytes()
    substitute(prompt.content, {"PROJECT_PATH": "X", "TASK": "Y"})
    assert prompt.path.read_bytes() == before


# ----------------------------------------------------------------------
# Prompt 数据对象
# ----------------------------------------------------------------------
def test_prompt_display_name() -> None:
    prompt = Prompt(
        id="A/b.md", path=Path("A/b.md"), name="b", category="A", content="x"
    )
    assert prompt.display_name == "A / b"
