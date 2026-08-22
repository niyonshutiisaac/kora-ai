"""Tests for the command safety classifier."""

import pytest

from kora.safety import SafetyLevel, classify_command, max_level


class TestDestructive:
    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf /",
            "rm -rf node_modules",
            "rm -r src/",
            "git reset --hard HEAD~1",
            "git push --force origin main",
            "git push -f",
            "sudo apt install anything",
            "shutdown /s",
            "DROP TABLE users;",
            "drop database shop",
            "Remove-Item -Recurse -Force build",
            "del /s /q *.tmp",
            ":(){ :|:& };:",
        ],
    )
    def test_destructive(self, cmd):
        assert classify_command(cmd).level is SafetyLevel.DESTRUCTIVE

    def test_reason_present(self):
        result = classify_command("git reset --hard")
        assert result.reason


class TestSafe:
    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la",
            "pwd",
            "cat README.md",
            "git status",
            "git log --oneline",
            "git diff HEAD~1",
            "python --version",
            "node -v",
            "grep -r TODO src/",
            "rg 'def main'",
            "dir",
            "echo hello",
            "whoami",
            "tree",
        ],
    )
    def test_safe(self, cmd):
        assert classify_command(cmd).level is SafetyLevel.SAFE


class TestModerate:
    @pytest.mark.parametrize(
        "cmd",
        [
            "pip install requests",
            "npm install",
            "npm run build",
            "yarn add axios",
            "pytest -q",
            "git add .",
            "git commit -m x",
            "git push origin main",
            "mkdir new_dir",
            "cp a b",
            "uvicorn app.main:app",
            "npx create-expo-app myapp",
            "black src/",
        ],
    )
    def test_moderate(self, cmd):
        assert classify_command(cmd).level is SafetyLevel.MODERATE

    def test_unknown_binary_is_moderate(self):
        assert classify_command("frobnicate --all").level is SafetyLevel.MODERATE


class TestMaxLevel:
    def test_ordering(self):
        assert max_level(SafetyLevel.SAFE, SafetyLevel.MODERATE) is SafetyLevel.MODERATE
        assert max_level(SafetyLevel.DESTRUCTIVE, SafetyLevel.SAFE) is SafetyLevel.DESTRUCTIVE
