"""验证输入、保存分支和跨表事务；仅使用内存模拟，不连接实际数据库。"""

import json
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock

import psycopg
import pytest

from thoth.db.connection import DatabaseError
from thoth.entity import WordEntity, TagEntity, WordTagEntity
from thoth.dto.word import WordInput
from thoth.service import add_update_words_service as service
from thoth.service.add_update_words_service import prepare_word_inputs, save_word_batch
from thoth.dto.request.add_update_words_request import WordWriteInput
from thoth.tools.add_update_words_tools import to_write_commands, to_write_response
from pydantic import TypeAdapter


def prepare_inputs(raw):
    """通过真实请求校验和入口映射构造业务输入，不解析字符串协议。"""
    return prepare_word_inputs(to_write_commands(TypeAdapter(list[WordWriteInput]).validate_python(raw)))


def serialize_word_batch(batch):
    """验证真实响应模型的对外序列化。"""
    return to_write_response(batch).model_dump(mode="json")


class MemoryTransaction:
    """模拟事务回滚恢复内存记录，支持在提交阶段注入错误；不模拟 PostgreSQL 锁。"""

    def __init__(self):
        """初始化内存单词和关联记录、事务计数以及一次性提交错误。"""
        self.words = {}
        self.links = {}
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = None
        self.active = False

    @contextmanager
    def transaction(self):
        """进入时快照记录；执行或提交失败时恢复快照，并统计事务结果。"""
        before_words = self.words.copy()
        before_links = {key: value[:] for key, value in self.links.items()}
        self.active = True
        try:
            yield
            if self.commit_error:
                error, self.commit_error = self.commit_error, None
                raise error
        except BaseException:
            self.words, self.links = before_words, before_links
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.active = False


@pytest.fixture
def repository(monkeypatch):
    """让三个模拟 Mapper 共用内存事务，验证保存流程及跨表失败回滚。"""
    connection = MemoryTransaction()
    repo = Mock(find_existing_words=Mock(return_value=[]))
    tags = Mock(find_by_codes=Mock(side_effect=lambda codes: [TagEntity(code=code) for code in codes]))
    links = Mock()

    def write(entity):
        """在活动事务中用 ID 为 7 的实体替换内存记录，模拟单词写入。"""
        assert connection.active
        saved = replace(entity, id=7)
        connection.words[entity.word] = saved
        return saved

    def delete(word_id):
        """在活动事务中清空指定单词的标签集合，模拟关联删除。"""
        assert connection.active
        connection.links[word_id] = []

    def insert_links(entities):
        """在活动事务中逐条追加标签，便于模拟部分插入后的失败。"""
        assert connection.active
        for entity in entities:
            connection.links.setdefault(entity.word_id, []).append(entity.tag_code)

    repo.insert.side_effect = write
    repo.update.side_effect = write
    links.delete_by_word_id.side_effect = delete
    links.insert_many.side_effect = insert_links
    repo.connection = connection
    repo.tags_mapper = tags
    repo.links_mapper = links
    monkeypatch.setattr(service, "WordTblMapper", Mock(return_value=repo))
    monkeypatch.setattr(service, "TagTblMapper", Mock(return_value=tags))
    monkeypatch.setattr(service, "WordTagTblMapper", Mock(return_value=links))
    return repo


def save_items(items, repository):
    """通过真实解析和 Service 流程处理输入，Mapper 由 fixture 隔离。"""
    return save_word_batch(prepare_inputs(items), repository.connection)


def complete_word(word="食べる"):
    """提供具有两个已有标签的完整新增请求。"""
    return {"word": word, "common_form": word, "hiragana": "たべる",
            "meaning": "吃", "tags": ["v", "v2"]}


@pytest.mark.parametrize("raw", [None, {}, "[]", [None], [42], [{"word": "a"}],
    [{"word": "a", "tags": ["v"], "operation": {"action": "create"}}],
    [{"word": "a", "tags": ["v"], "action": "delete"}],
    [{"word": "a", "tags": ["v"], "meaning": 42}],
    [{"word": "a", "tags": ["v"], "unknown": 1}]])
def test_structure_errors_rejected_before_business(repository, raw):
    with pytest.raises(ValueError):
        prepare_inputs(raw)
    repository.find_existing_words.assert_not_called()
    repository.insert.assert_not_called()


@pytest.mark.parametrize("word", ["", " \t"])
def test_business_invalid_word_fails_without_touching_repository(repository, word):
    result = save_items([{"word": word, "tags": ["v"]}], repository)
    assert result.results[0].status == "failed"
    repository.find_existing_words.assert_not_called()


def test_prepare_retains_business_errors_and_valid_entities():
    items = prepare_inputs([{"word": "", "tags": ["v"]}, {"word": "食べる", "tags": ["v"]}])
    assert all(isinstance(item, WordInput) for item in items)
    assert items[0].error
    assert items[1].error is None
    assert items[1].entity == WordEntity(word="食べる")
    assert items[1].tags == ("v",)
    assert items[1].action == "create"


@pytest.mark.parametrize("tags", [None, [], "v", {}, [None], [1], [True], [""], [" "],
                                  [" v"], ["v "], ["動詞"], ["v-1"], ["x" * 33], ["v\n"], ["\ud800"]])
@pytest.mark.parametrize("action", ["create", "update"])
def test_invalid_tags_fail_without_database_access(repository, tags, action):
    item = complete_word()
    item.update(tags=tags, action=action)
    with pytest.raises(ValueError):
        save_items([item], repository)
    repository.find_existing_words.assert_not_called()
    assert repository.connection.commits == 0


@pytest.mark.parametrize("action", ["create", "update"])
def test_missing_tags_is_rejected(repository, action):
    item = complete_word()
    del item["tags"]
    item["action"] = action
    with pytest.raises(ValueError):
        save_items([item], repository)
    repository.find_existing_words.assert_not_called()


def test_tags_are_deduplicated_without_changing_case():
    item = complete_word()
    item["tags"] = ["v", "v2", "v", "V", "a" * 32]
    assert prepare_inputs([item])[0].tags == ("v", "v2", "V", "a" * 32)


def test_create_preserves_entity_and_writes_tags_in_one_transaction(repository):
    requests = prepare_inputs([complete_word()])
    result = save_word_batch(requests, repository.connection)
    assert repository.insert.call_args.args[0] is requests[0].entity
    repository.find_existing_words.assert_called_once_with(["食べる"])
    repository.links_mapper.delete_by_word_id.assert_called_once_with(7)
    assert repository.links_mapper.insert_many.call_args.args[0] == [
        WordTagEntity(word_id=7, tag_code=code)
        for code in ("v", "v2")
    ]
    assert serialize_word_batch(result) == {"results": [{"index": 0, "word": "食べる", "status": "created"}]}
    assert repository.connection.commits == 1


@pytest.mark.parametrize("empty", [None, "", " \t\n"])
def test_update_ignores_empty_information_and_preserves_nonempty_text(repository, empty):
    repository.find_existing_words.return_value = [WordEntity(word=" 食べる ")]
    result = save_items([{"word": " 食べる ", "common_form": empty, "meaning": " 吃 ",
                          "tags": ["v"], "action": "update"}], repository)
    repository.update.assert_called_once_with(WordEntity(word=" 食べる ", meaning=" 吃 "))
    assert result.results[0].status == "updated"
    assert repository.connection.links == {7: ["v"]}


def test_tags_only_update_and_identical_lists_always_replace(repository):
    repository.find_existing_words.return_value = [WordEntity(word="食べる")]
    repository.connection.links = {7: ["v", "v2"], 8: ["n"]}
    events = Mock()
    events.attach_mock(repository.update, "update")
    events.attach_mock(repository.links_mapper.delete_by_word_id, "delete")
    events.attach_mock(repository.links_mapper.insert_many, "insert")
    result = save_items([{"word": "食べる", "tags": ["v", "v2"],
                          "action": "update"}], repository)
    assert result.results[0].status == "updated"
    assert [call[0] for call in events.mock_calls] == ["update", "delete", "insert"]
    assert repository.connection.links == {7: ["v", "v2"], 8: ["n"]}


def test_existing_create_validates_tags_but_never_writes(repository):
    repository.find_existing_words.return_value = [WordEntity(word="食べる")]
    result = save_items([{"word": "食べる", "tags": ["v"]}], repository)
    assert result.results[0].status == "skipped"
    repository.tags_mapper.find_by_codes.assert_called_once_with(["v"])
    repository.insert.assert_not_called()
    repository.update.assert_not_called()
    repository.links_mapper.delete_by_word_id.assert_not_called()
    repository.links_mapper.insert_many.assert_not_called()


@pytest.mark.parametrize("action", ["create", "update"])
def test_missing_new_fields_are_reported_and_next_item_succeeds(repository, action):
    result = save_items([{"word": "食べる", "meaning": "吃", "tags": ["v"],
                          "action": action}, complete_word("飲む")], repository)
    assert [row.status for row in result.results] == ["failed", "created"]
    assert result.results[0].fields == ("common_form", "hiragana")
    assert serialize_word_batch(result)["results"][0]["fields"] == ["common_form", "hiragana"]
    assert repository.insert.call_count == 1


@pytest.mark.parametrize("action", ["create", "update"])
def test_unknown_tag_prevents_all_writes_even_for_existing_create(repository, action):
    repository.find_existing_words.return_value = [WordEntity(word="食べる")]
    repository.tags_mapper.find_by_codes.side_effect = None
    repository.tags_mapper.find_by_codes.return_value = [TagEntity(code="v")]
    result = save_items([{**complete_word(), "action": action}], repository)
    assert result.results[0].status == "failed"
    assert "v2" in result.results[0].reason
    repository.insert.assert_not_called()
    repository.update.assert_not_called()
    repository.links_mapper.delete_by_word_id.assert_not_called()
    assert repository.connection.rollbacks == 1


@pytest.mark.parametrize("action,expected", [("create", "skipped"), ("update", "updated")])
def test_concurrent_insert_conflict(repository, action, expected):
    repository.insert.side_effect = None
    repository.insert.return_value = None
    result = save_items([{**complete_word(), "action": action}], repository)
    assert result.results[0].status == expected
    assert repository.update.call_count == (action == "update")
    assert repository.links_mapper.insert_many.call_count == (action == "update")


@pytest.mark.parametrize("exists", [False, True])
def test_external_deletion_causes_failure_without_label_writes(repository, exists):
    repository.find_existing_words.return_value = [WordEntity(word="食べる")] if exists else []
    repository.insert.side_effect = repository.update.side_effect = None
    repository.insert.return_value = repository.update.return_value = None
    result = save_items([{**complete_word(), "action": "update"}], repository)
    assert result.results[0].status == "failed"
    assert "记录发生变化" in result.results[0].reason
    repository.links_mapper.delete_by_word_id.assert_not_called()
    assert repository.connection.rollbacks == 1


@pytest.mark.parametrize("phase", ["lookup_tags", "word", "delete", "partial_insert", "commit"])
@pytest.mark.parametrize("exists", [False, True])
def test_failure_rolls_back_word_and_all_labels_and_next_item_succeeds(repository, phase, exists):
    connection = repository.connection
    old = WordEntity(id=7, word="食べる", meaning="旧释义")
    connection.words = {"食べる": old} if exists else {}
    connection.links = {7: ["n", "adv"]} if exists else {}
    repository.find_existing_words.return_value = [old] if exists else []
    before_words, before_links = connection.words.copy(), connection.links.copy()
    error = psycopg.errors.ForeignKeyViolation("secret SQL and credentials")
    target = {"lookup_tags": repository.tags_mapper.find_by_codes,
              "word": repository.update if exists else repository.insert,
              "delete": repository.links_mapper.delete_by_word_id,
              "partial_insert": repository.links_mapper.insert_many}.get(phase)
    if target is not None:
        original = target.side_effect
        def fail_once(*args):
            """只注入一次故障；关联插入场景先写入一条记录，以验证部分写入也会回滚。"""
            target.side_effect = original
            if phase == "partial_insert":
                connection.links[7].append(args[0][0].tag_code)
            raise error
        target.side_effect = fail_once
    else:
        connection.commit_error = error
    item = {**complete_word(), "action": "update"}
    result = save_items([item], repository)
    assert result.results[0].status == "failed"
    assert "secret" not in result.results[0].reason
    assert "23503" in result.results[0].reason
    assert connection.words == before_words
    assert connection.links == before_links
    assert connection.rollbacks == 1 and connection.commits == 0
    result = save_items([complete_word("飲む")], repository)
    assert result.results[0].status == "created"
    assert connection.commits == 1


def test_single_item_failure_does_not_stop_same_batch(repository):
    original = repository.insert.side_effect
    def insert(entity):
        """仅让指定单词写入失败，其他单词调用正常的内存写入流程。"""
        if entity.word == "食べる":
            raise psycopg.errors.CheckViolation("secret")
        return original(entity)
    repository.insert.side_effect = insert
    result = save_items([complete_word(), complete_word("飲む")], repository)
    assert [row.status for row in result.results] == ["failed", "created"]
    assert repository.connection.rollbacks == repository.connection.commits == 1


def test_invalid_duplicate_blocks_valid_duplicate_but_not_other_items(repository):
    result = save_items([complete_word(), {"word": "食べる", "tags": ["v"], "meaning": "\x00"}, complete_word("飲む")], repository)
    assert [row.status for row in result.results] == ["failed", "failed", "created"]
    assert "重复" in result.results[0].reason
    repository.find_existing_words.assert_called_once_with(["飲む"])


def test_one_lookup_covers_90_new_words_and_10_partial_updates(repository):
    words = [f"単語{index:03d}" for index in range(100)]
    existing = set(words[::10])
    repository.find_existing_words.return_value = [WordEntity(word=word) for word in existing]
    items = [{"word": word, "meaning": "更新", "tags": ["v"], "action": "update"}
             if word in existing else complete_word(word) for word in words]
    result = save_items(items, repository)
    repository.find_existing_words.assert_called_once_with(words)
    assert repository.insert.call_count == 90 and repository.update.call_count == 10
    assert [row.status for row in result.results] == ["updated" if word in existing else "created" for word in words]
    assert [row.index for row in result.results] == list(range(100))
    assert repository.connection.commits == 100


def test_batch_lookup_error_is_sanitized_and_prevents_writes(repository):
    repository.find_existing_words.side_effect = psycopg.errors.UndefinedTable("secret")
    with pytest.raises(DatabaseError, match="42P01") as caught:
        save_items([complete_word()], repository)
    assert "secret" not in str(caught.value)
    repository.insert.assert_not_called()
    assert repository.connection.commits == 0


@pytest.mark.parametrize("word", ["食\x00べる", "\ud800"])
def test_invalid_word_does_not_disrupt_valid_item(repository, word):
    result = save_items([complete_word(word), complete_word("飲む")], repository)
    assert [row.status for row in result.results] == ["failed", "created"]
    repository.find_existing_words.assert_called_once_with(["飲む"])
    json.dumps(serialize_word_batch(result), ensure_ascii=False).encode("utf-8")
