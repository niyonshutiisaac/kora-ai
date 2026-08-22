"""Tests for i18n: detection, translations, aliases."""

from kora import i18n


class TestDetectLanguage:
    def test_kinyarwanda_imperative_short(self):
        assert i18n.detect_language("Kora porogaramu ya FastAPI") == "rw"

    def test_kinyarwanda_longer(self):
        text = "Nyamuneka andika dosiye niba ubifite, hanyuma urebe ko byora neza"
        assert i18n.detect_language(text) == "rw"

    def test_english(self):
        assert i18n.detect_language("Please write the file and then run the tests") == "en"

    def test_code_like_text_is_english(self):
        assert i18n.detect_language("def main(): return 42") == "en"

    def test_empty_is_english(self):
        assert i18n.detect_language("") == "en"

    def test_resolve_auto(self):
        assert i18n.resolve_language("auto", "andika") == "rw"
        assert i18n.resolve_language("auto", "write it") == "en"

    def test_resolve_forced(self):
        assert i18n.resolve_language("rw", "hello") == "rw"
        assert i18n.resolve_language("en", "kora ibi") == "en"


class TestTranslations:
    def test_required_keys_both_languages(self):
        required = {
            "welcome": "Murakaza neza",
            "enter_command": None,
            "model": "Moderi",
            "tools": "Ibikoresho",
            "file": "Dosiye",
            "confirm": "Emeza",
            "cancel": "Hagarika",
            "run_command": "Koresha itegeko?",
            "error": "Ikosa",
        }
        for key, expected_rw in required.items():
            assert key in i18n.TRANSLATIONS
            rw = i18n.tr(key, "rw")
            en = i18n.tr(key, "en")
            assert rw and en
            if expected_rw:
                assert expected_rw in rw
            assert rw != en

    def test_fallback_to_key(self):
        assert i18n.tr("nonexistent_key", "en") == "nonexistent_key"


class TestCommandAliases:
    def test_aliases_map_to_canonical(self):
        assert i18n.normalize_command("/fasha") == "/help"
        assert i18n.normalize_command("/moderi groq llama-3.3-70b-versatile") == (
            "/model groq llama-3.3-70b-versatile"
        )
        assert i18n.normalize_command("/ibikoresho") == "/tools"
        assert i18n.normalize_command("/hagarika") == "/cancel"
        assert i18n.normalize_command("/sohoka") == "/quit"

    def test_non_alias_passthrough(self):
        assert i18n.normalize_command("/help me now") == "/help me now"
        assert i18n.normalize_command("kora app") == "kora app"

    def test_language_prompt_rule_verbatim(self):
        assert i18n.LANGUAGE_PROMPT_RULE.startswith("The user may write in English or Kinyarwanda.")
        assert "same language" in i18n.LANGUAGE_PROMPT_RULE
