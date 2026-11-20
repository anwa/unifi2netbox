"""The user manual: structure, links, images and the in-app viewer."""

import re
from pathlib import Path

from PySide6.QtCore import QUrl

from unifi2netbox.gui_manual import ManualWindow
from unifi2netbox.manual import build_toc, manual_root, title_of

ROOT = Path(__file__).resolve().parents[1] / "manual"
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def pages():
    return sorted(ROOT.rglob("*.md"))


def test_manual_is_found_and_starts_with_the_overview():
    assert manual_root() == ROOT
    toc = build_toc(ROOT)
    assert toc.title == "Overview"
    assert [entry.title for entry in toc.children] == [
        "Getting started",
        "Settings",
        "The review window",
        "Device types",
        "Applying changes",
        "Reference",
        "Backup and restore",
    ]
    assert all(entry.children for entry in toc.children)


def test_every_folder_has_an_index_and_every_page_a_title():
    for folder in [ROOT, *[p for p in ROOT.rglob("*") if p.is_dir()]]:
        if folder.name != "images":
            assert (folder / "index.md").is_file(), folder
    for page in pages():
        assert page.read_text(encoding="utf-8").startswith("# "), page


def test_links_and_images_resolve():
    referenced = set()
    for page in pages():
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://")):
                continue
            path = (page.parent / target.split("#", 1)[0]).resolve()
            assert path.is_file(), f"{page.relative_to(ROOT)} -> {target}"
            referenced.add(path)
    images = {p.resolve() for p in (ROOT / "images").glob("*.png")}
    assert images and images <= referenced, images - referenced


def test_titles_fall_back_to_the_file_name(tmp_path):
    page = tmp_path / "02-first-steps.md"
    page.write_text("no heading\n", encoding="utf-8")

    assert title_of(page) == "First steps"


def test_viewer_shows_the_overview_and_follows_the_tree(qtbot):
    window = ManualWindow()
    qtbot.addWidget(window)

    assert window.current_page() == (ROOT / "index.md").resolve()
    assert window.tree.currentItem().text(0) == "Overview"
    assert "UniFi is only ever read" in window.browser.toPlainText()

    settings = window.items[(ROOT / "02-settings" / "index.md").resolve()]
    window.tree.setCurrentItem(settings)
    assert window.current_page() == (ROOT / "02-settings" / "index.md").resolve()
    assert window.back_button.isEnabled()

    window.browser.setSource(
        QUrl.fromLocalFile(str(ROOT / "02-settings" / "01-netbox.md"))
    )
    assert window.tree.currentItem().text(0) == "NetBox"
    window.home_button.click()
    assert window.tree.currentItem().text(0) == "Overview"


def test_viewer_without_manual_explains_it(qtbot, tmp_path):
    window = ManualWindow(root=tmp_path / "nowhere")
    qtbot.addWidget(window)

    assert "not installed" in window.browser.toPlainText()
    assert not window.tree.isEnabled() and not window.home_button.isEnabled()


def test_main_window_opens_the_manual(qtbot, tmp_path):
    from PySide6.QtCore import QThreadPool

    from unifi2netbox.gui import MainWindow

    window = MainWindow(tmp_path / "config.toml", QThreadPool(), open_first_run=False)
    qtbot.addWidget(window)
    window.manual_button.click()

    assert window.manual_window is not None and window.manual_window.isVisible()
    window.show_manual("03-review/05-cables.md")
    assert window.manual_window.tree.currentItem().text(0) == "Cables"


def test_search_finds_pages_with_every_word_best_first(tmp_path):
    from unifi2netbox.manual import plain_text, search_manual

    (tmp_path / "index.md").write_text("# Overview\n\nSee [Backup](b.md).\n", "utf-8")
    (tmp_path / "b.md").write_text(
        "# Backup\n\n![shot](x.png)\n\nThe **backup** file holds the data.\n", "utf-8"
    )
    (tmp_path / "c.md").write_text("# Other\n\nA backup is mentioned once.\n", "utf-8")
    hits = search_manual(tmp_path, "BACKUP")
    assert [h.title for h in hits] == ["Backup", "Other", "Overview"]
    assert "backup file holds" in hits[0].snippet
    assert [h.title for h in search_manual(tmp_path, "backup data")] == ["Backup"]
    assert search_manual(tmp_path, "nothing-like-this") == []
    assert search_manual(tmp_path, "   ") == []
    assert plain_text("See [the page](p.md) and ![x](y.png) `code`") == (
        "See the page and code"
    )


def test_viewer_search_lists_pages_marks_words_and_moves_between_them(qtbot):
    window = ManualWindow(root=ROOT)
    qtbot.addWidget(window)
    window.search.setText("host name")
    window.run_search()
    assert window.left.currentIndex() == 1
    assert window.results.count() >= 2
    assert "found" in window.results_label.text()

    from PySide6.QtCore import Qt

    titles = [
        window.results.item(i).data(Qt.ItemDataRole.AccessibleTextRole).split("\n")[0]
        for i in range(window.results.count())
    ]
    label = window.results.itemWidget(window.results.item(titles.index("Restore")))
    assert "<b>host</b> <b>name</b>" in label.text()  # words marked
    restore = titles.index("Restore")
    window._open_result(window.results.item(restore))
    assert window.current_page().name == "02-restore.md"
    assert window.match_count() >= 2  # "host" and "name" marked
    first = window.browser.textCursor().position()
    assert window.find_next() and window.browser.textCursor().position() != first

    window.end_search()
    assert window.left.currentIndex() == 0 and window.match_count() == 0

    window.search.setText("xyzzy-nothing")
    window.run_search()
    assert (
        window.results.count() == 0 and window.results_label.text() == "Nothing found."
    )
