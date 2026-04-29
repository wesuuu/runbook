import pytest

from app.services.data.text_chunker import TextChunk, chunk_text


class TestEmptyAndShortTexts:
    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_text("   \n\n  ") == []

    def test_short_text_returns_single_chunk(self):
        text = "This is a short sentence."
        result = chunk_text(text, chunk_size=100)
        assert len(result) == 1
        assert result[0].content == text
        assert result[0].chunk_index == 0
        assert result[0].token_count == 5


class TestSplitting:
    def test_splits_on_paragraph_breaks_first(self):
        paragraphs = ["Word " * 80 for _ in range(5)]
        text = "\n\n".join(paragraphs)
        result = chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) > 1
        # Each chunk should contain coherent paragraph content
        for chunk in result:
            assert chunk.content.strip()

    def test_splits_on_newlines_when_no_paragraphs(self):
        lines = ["Line " * 60 for _ in range(5)]
        text = "\n".join(lines)
        result = chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) > 1

    def test_splits_on_sentence_endings_when_no_newlines(self):
        sentences = ["This is sentence number " + str(i) + ". " for i in range(200)]
        text = " ".join(sentences)
        result = chunk_text(text, chunk_size=50, overlap=5)
        assert len(result) > 1

    def test_splits_on_spaces_as_last_resort(self):
        # A single long "paragraph" with no sentence endings
        text = "word " * 500
        result = chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) > 1
        for chunk in result:
            assert chunk.token_count <= 150  # Allow some slack


class TestOverlap:
    def test_overlap_between_chunks(self):
        text = " ".join([f"word{i}" for i in range(300)])
        result = chunk_text(text, chunk_size=100, overlap=20)
        assert len(result) > 1
        # Check that consecutive chunks share some content
        for i in range(len(result) - 1):
            words_a = set(result[i].content.split())
            words_b = set(result[i + 1].content.split())
            overlap = words_a & words_b
            assert len(overlap) > 0, "Consecutive chunks should share words"


class TestChunkProperties:
    def test_chunk_indices_are_sequential(self):
        text = "Word " * 500
        result = chunk_text(text, chunk_size=50, overlap=5)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_token_count_is_populated(self):
        text = "Hello world this is a test"
        result = chunk_text(text, chunk_size=100)
        assert len(result) == 1
        assert result[0].token_count == 6


class TestPageBoundaries:
    def test_page_boundaries_assign_page_numbers(self):
        page1 = "This is page one content. " * 20
        page2 = "This is page two content. " * 20
        page3 = "This is page three content. " * 20
        text = page1 + page2 + page3
        boundaries = [len(page1), len(page1) + len(page2)]

        result = chunk_text(text, chunk_size=50, overlap=5, page_boundaries=boundaries)
        assert len(result) > 0
        # At least one chunk should have a page number assigned
        page_numbers = [c.page_number for c in result if c.page_number is not None]
        assert len(page_numbers) > 0

    def test_no_page_boundaries_gives_none(self):
        text = "Word " * 50
        result = chunk_text(text, chunk_size=100)
        assert all(c.page_number is None for c in result)


class TestLargeText:
    def test_large_text_produces_expected_count(self):
        # 10000 words, chunk_size 1000 -> roughly 10+ chunks
        text = " ".join([f"word{i}" for i in range(10000)])
        result = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(result) >= 8
        assert len(result) <= 20


class TestUnicode:
    def test_unicode_and_special_chars(self):
        text = (
            "Ceci est un texte en francais avec des accents: "
            + "e\u0301, a\u0300, u\u0302. "
            + "\u4e2d\u6587\u6d4b\u8bd5\u6587\u672c\u3002"
            + "Emoji test: \U0001f600\U0001f680\U0001f4a1. "
        ) * 50
        result = chunk_text(text, chunk_size=30, overlap=5)
        assert len(result) > 0
        # All chunks should have content
        for chunk in result:
            assert chunk.content.strip()
            assert chunk.token_count > 0
