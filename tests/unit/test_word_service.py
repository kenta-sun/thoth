"""Word input and batch behavior, without a database or external service."""

import json
from unittest.mock import Mock

import pytest

from thoth.db.connection import DatabaseError
from thoth.db.word_repo import MissingWordFieldsError, SaveResult
from thoth.word_service import parse_words_text, save_word_batch


@pytest.fixture
def repository():
    return Mock(
        find_existing_words=Mock(return_value=set()),
        save=Mock(return_value=SaveResult(status="created")),
    )


def complete_word(word="食べる"):
    return {
        "word": word,
        "common_form": word,
        "hiragana": "たべる",
        "meaning": "吃",
    }


@pytest.mark.parametrize(
    "text",
    [
        "not json", "{}", "null", "[]", '"words"',
        '[{"word":"食べる","word":"飲む"}]',
        '[{"word":"食べる","operation":{"action":"create","action":"update"}}]',
        '[{"word":"食べる","meaning":NaN}]',
        '[{"word":"食べる","meaning":Infinity}]',
        '[{"word":"食べる","meaning":-Infinity}]',
    ],
)
def test_rejects_invalid_json_batch(text):
    with pytest.raises(ValueError):
        parse_words_text(text)


def test_parse_retains_invalid_elements_for_individual_errors():
    assert parse_words_text('[null,42,{"word":"食べる"}]') == [None, 42, {"word": "食べる"}]


def test_omitting_operation_defaults_to_create(repository):
    result = save_word_batch(parse_words_text(json.dumps([complete_word()])), repository)

    repository.save.assert_called_once_with(
        word="食べる", action="create", exists=False,
        values={"common_form": "食べる", "hiragana": "たべる", "meaning": "吃"},
    )
    repository.find_existing_words.assert_called_once_with(["食べる"])
    assert result["results"][0] == {"index": 0, "word": "食べる", "status": "created"}


@pytest.mark.parametrize("empty_value", [None, "", " \t\n"])
def test_update_ignores_empty_fields(repository, empty_value):
    repository.find_existing_words.return_value = {"食べる"}
    repository.save.return_value = SaveResult(status="updated")
    result = save_word_batch([{
        "word": "食べる", "meaning": "吃；食用", "common_form": empty_value,
        "operation": {"action": "update"},
    }], repository)

    repository.save.assert_called_once_with(
        word="食べる", action="update", exists=True,
        values={"common_form": None, "hiragana": None, "meaning": "吃；食用"},
    )
    assert result["results"][0]["status"] == "updated"


def test_nonempty_input_values_are_preserved(repository):
    repository.find_existing_words.return_value = {" 食べる "}
    save_word_batch([{
        "word": " 食べる ", "meaning": " 吃 ", "operation": {"action": "update"},
    }], repository)
    assert repository.save.call_args.kwargs["word"] == " 食べる "
    assert repository.save.call_args.kwargs["values"]["meaning"] == " 吃 "
    repository.find_existing_words.assert_called_once_with([" 食べる "])


@pytest.mark.parametrize("item", [
    {}, {"word": None}, {"word": ""}, {"word": " \t"}, {"word": 42},
    None, 42, [], "食べる",
    {"word": "食べる", "meaning": 42},
    {"word": "食べる", "meaning": "吃\x00食用"},
    {"word": "食べる", "hiragana": ["たべる"]},
    {"word": "食べる", "common_form": False},
    {"word": "食べる", "created_at": "2026-10-10"},
    {"word": "食べる", "sql": "DROP TABLE word_tbl"},
    {"word": "食べる", "operation": None},
    {"word": "食べる", "operation": "update"},
    {"word": "食べる", "operation": {}},
    {"word": "食べる", "operation": {"action": "UPDATE"}},
    {"word": "食べる", "operation": {"action": "delete"}},
    {"word": "食べる", "operation": {"action": ["update"]}},
    {"word": "食べる", "operation": {"action": "update", "sql": "DROP TABLE word_tbl"}},
])
def test_invalid_item_fails_without_touching_repository(repository, item):
    result = save_word_batch([item], repository)

    repository.save.assert_not_called()
    repository.find_existing_words.assert_not_called()
    assert result["results"][0]["index"] == 0
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["reason"]


def test_duplicate_words_all_fail_but_other_items_continue(repository):
    result = save_word_batch([
        complete_word(), complete_word("飲む"),
        {"word": "食べる", "meaning": "吃；食用", "operation": {"action": "update"}},
        {"word": "走る", "sql": "SELECT * FROM word_tbl"},
        None,
    ], repository)

    assert [row["status"] for row in result["results"]] == ["failed", "created", "failed", "failed", "failed"]
    assert [row["index"] for row in result["results"]] == [0, 1, 2, 3, 4]
    repository.find_existing_words.assert_called_once_with(["飲む"])
    repository.save.assert_called_once()
    assert repository.save.call_args.kwargs["word"] == "飲む"


def test_missing_fields_on_new_word_reported_and_next_word_processed(repository):
    repository.save.side_effect = [
        MissingWordFieldsError(["common_form", "hiragana"]),
        SaveResult(status="created"),
    ]
    result = save_word_batch([
        {"word": "食べる", "meaning": "吃", "operation": {"action": "update"}},
        complete_word("飲む"),
    ], repository)

    assert [row["status"] for row in result["results"]] == ["failed", "created"]
    assert result["results"][0]["fields"] == ["common_form", "hiragana"]
    assert repository.save.call_count == 2


def test_database_failure_does_not_stop_batch(repository):
    repository.save.side_effect = [
        DatabaseError("保存单词失败，请稍后重试。"),
        SaveResult(status="created"),
    ]
    result = save_word_batch([complete_word(), complete_word("飲む")], repository)

    assert [row["status"] for row in result["results"]] == ["failed", "created"]
    assert result["results"][0]["reason"]


def test_skipped_repository_result_preserves_reason(repository):
    repository.find_existing_words.return_value = {"食べる"}
    repository.save.return_value = SaveResult(status="skipped", reason="单词已存在。")
    result = save_word_batch([complete_word()], repository)
    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["reason"] == "单词已存在。"


@pytest.mark.parametrize("action", ["create", "update"])
def test_missing_information_is_left_to_existing_or_new_word_decision(repository, action):
    repository.find_existing_words.return_value = {"食べる"}
    repository.save.return_value = SaveResult(status="skipped")
    result = save_word_batch([{"word": "食べる", "operation": {"action": action}}], repository)

    repository.save.assert_called_once_with(
        word="食べる", action=action, exists=True,
        values={"common_form": None, "hiragana": None, "meaning": None},
    )
    assert result["results"][0]["status"] == "skipped"


def test_one_lookup_covers_90_new_words_and_10_partial_updates(repository):
    words = [f"単語{index:03d}" for index in range(100)]
    existing_words = set(words[::10])
    items = [
        {"word": word, "meaning": "更新后的释义", "operation": {"action": "update"}}
        if word in existing_words else complete_word(word)
        for word in words
    ]

    def find_existing_words(requested_words):
        repository.save.assert_not_called()
        assert requested_words == words
        return existing_words

    repository.find_existing_words.side_effect = find_existing_words
    repository.save.side_effect = lambda **request: SaveResult(
        status="updated" if request["exists"] else "created"
    )

    result = save_word_batch(items, repository)

    repository.find_existing_words.assert_called_once_with(words)
    assert repository.save.call_count == 100
    for word, save_call in zip(words, repository.save.call_args_list, strict=True):
        assert save_call.kwargs["word"] == word
        assert save_call.kwargs["exists"] is (word in existing_words)
    assert [row["word"] for row in result["results"]] == words
    assert [row["index"] for row in result["results"]] == list(range(100))
    assert [row["status"] for row in result["results"]] == [
        "updated" if word in existing_words else "created" for word in words
    ]


def test_failed_batch_lookup_stops_before_any_write(repository):
    repository.find_existing_words.side_effect = DatabaseError("查询单词失败，请稍后重试。")

    with pytest.raises(DatabaseError, match="查询单词失败"):
        save_word_batch([complete_word(), complete_word("飲む")], repository)

    repository.find_existing_words.assert_called_once_with(["食べる", "飲む"])
    repository.save.assert_not_called()


@pytest.mark.parametrize("invalid_word", ["食\x00べる", "\ud800"])
def test_invalid_database_word_does_not_disrupt_batch_lookup(repository, invalid_word):
    result = save_word_batch([complete_word(invalid_word), complete_word("飲む")], repository)

    repository.find_existing_words.assert_called_once_with(["飲む"])
    repository.save.assert_called_once()
    assert repository.save.call_args.kwargs["word"] == "飲む"
    assert [row["status"] for row in result["results"]] == ["failed", "created"]
    assert [row["index"] for row in result["results"]] == [0, 1]
    if invalid_word == "\ud800":
        assert result["results"][0]["word"] is None
