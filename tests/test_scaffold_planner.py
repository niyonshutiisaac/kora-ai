"""Tests for scaffold templates and the planner."""

import pytest

from kora.agent.planner import Planner
from kora.tools.scaffold_templates import scaffold_files


class TestScaffoldTemplates:
    def test_fastapi_files_render(self):
        files = scaffold_files("fastapi", "shop-api")
        assert "app/main.py" in files
        assert "app/routers/items.py" in files
        main = files["app/main.py"]
        assert "{{" not in main  # all format placeholders resolved
        assert '"/health"' in main
        # f-string style route params survive formatting:
        items = files["app/routers/items.py"]
        assert "{item_id}" in items

    def test_react_files_render(self):
        files = scaffold_files("react", "my-app")
        assert "src/App.tsx" in files
        app_tsx = files["src/App.tsx"]
        assert "useState" in app_tsx
        assert "{{" not in app_tsx
        pkg = files["package.json"]
        assert '"vite"' in pkg

    def test_expo_files_render(self):
        files = scaffold_files("expo", "mobile")
        navigation = files["src/navigation/index.tsx"]
        assert "itemId" in navigation
        assert "{{" not in navigation
        detail = files["src/screens/DetailScreen.tsx"]
        assert "route.params.itemId" in detail

    def test_flutter_files_render_snake_case(self):
        files = scaffold_files("flutter", "my_app")
        dart = files["lib/main.dart"]
        assert "my_app" in files["test/widget_test.dart"]
        assert "KoraApp" in dart

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown project_type"):
            scaffold_files("cobol", "mainframe")

    def test_all_types_render_without_format_errors(self):
        """format() must fully succeed - any KeyError/IndexError fails the run."""
        for ptype in ("fastapi", "react", "nextjs", "expo", "flutter"):
            files = scaffold_files(ptype, "demo")
            assert files, ptype
            # unresolved placeholders like {name} or {snake_name} must be gone
            for rel, content in files.items():
                assert "{name}" not in content, f"{ptype}/{rel}"
                assert "{snake_name}" not in content, f"{ptype}/{rel}"
                assert "{title}" not in content, f"{ptype}/{rel}"


class TestPlanner:
    def test_progress_counts(self):
        planner = Planner()
        planner.replace_all(
            [
                {"id": 1, "content": "a", "status": "completed"},
                {"id": 2, "content": "b", "status": "in_progress"},
                {"id": 3, "content": "c", "status": "pending"},
            ]
        )
        done, total = planner.progress
        assert (done, total) == (1, 3)
        assert planner.in_progress["content"] == "b"

    def test_render_contains_items(self):
        planner = Planner()
        planner.replace_all([{"id": 1, "content": "write tests", "status": "in_progress"}])
        rendered = planner.render()
        assert "[~] write tests" in rendered
