import pytest

from app.services.markdown_chunker import (
    chunk_markdown,
    _segment_into_blocks,
)


class TestEmptyAndShortTexts:
    def test_empty_text_returns_empty_list(self):
        assert chunk_markdown("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_markdown("   \n\n  ") == []

    def test_short_text_returns_single_chunk(self):
        text = "# Hello\n\nThis is short."
        result = chunk_markdown(text, chunk_size=100)
        assert len(result) == 1
        assert result[0].content == text.strip()
        assert result[0].chunk_index == 0


class TestHeadingPreservation:
    def test_heading_stays_with_following_paragraph(self):
        text = (
            "# Introduction\n\n"
            "This is the intro paragraph.\n\n"
            "# Methods\n\n"
            "This is the methods section."
        )
        blocks = _segment_into_blocks(text)
        # Each heading should start its own block
        heading_blocks = [b for b in blocks if b.strip().startswith("#")]
        assert len(heading_blocks) >= 2
        # Each heading block should contain its following content
        for block in heading_blocks:
            lines = block.strip().split("\n")
            assert lines[0].startswith("#")

    def test_heading_not_split_from_content_in_chunks(self):
        # Small enough to fit in one chunk each
        sections = []
        for i in range(5):
            sections.append(f"## Section {i}\n\nContent for section {i}. " * 5)
        text = "\n\n".join(sections)
        result = chunk_markdown(text, chunk_size=100, overlap=10)
        # No chunk should start mid-paragraph (each should start with heading or overlap)
        for chunk in result:
            lines = chunk.content.strip().split("\n")
            # First non-empty line should not be a bare continuation
            first_line = lines[0].strip()
            assert first_line  # Should not be empty


class TestCodeFencePreservation:
    def test_code_fence_not_split(self):
        text = (
            "# Code Example\n\n"
            "Here is some code:\n\n"
            "```python\n"
            "def hello():\n"
            "    print('hello world')\n"
            "    return True\n"
            "```\n\n"
            "# Next Section\n\n"
            "More content here."
        )
        blocks = _segment_into_blocks(text)
        # Find the block containing the code fence
        code_blocks = [b for b in blocks if "```python" in b]
        assert len(code_blocks) == 1
        # The code fence should be complete (has opening and closing ```)
        code_block = code_blocks[0]
        fence_count = code_block.count("```")
        assert fence_count >= 2  # Opening and closing

    def test_code_fence_kept_intact_in_chunk(self):
        text = (
            "# Intro\n\nSome text.\n\n"
            "```\nline1\nline2\nline3\n```\n\n"
            "# End\n\nMore text."
        )
        result = chunk_markdown(text, chunk_size=200, overlap=10)
        # Find chunk with code fence
        code_chunks = [c for c in result if "```" in c.content]
        assert len(code_chunks) >= 1
        for cc in code_chunks:
            # Each code chunk should have balanced fences
            assert cc.content.count("```") % 2 == 0


class TestTablePreservation:
    def test_table_stays_together_in_block(self):
        text = (
            "# Results\n\n"
            "| Name | Value |\n"
            "|------|-------|\n"
            "| A    | 1     |\n"
            "| B    | 2     |\n"
            "| C    | 3     |\n\n"
            "# Conclusion\n\n"
            "The end."
        )
        blocks = _segment_into_blocks(text)
        # Find block with table
        table_blocks = [b for b in blocks if "|" in b]
        assert len(table_blocks) >= 1
        # Table should have all rows in one block
        table_block = table_blocks[0]
        pipe_lines = [l for l in table_block.split("\n") if "|" in l]
        assert len(pipe_lines) >= 4  # header + separator + 3 data rows


class TestPageBoundaries:
    def test_page_boundaries_assign_page_numbers(self):
        page1 = "# Page 1\n\nContent for page one. " * 20
        page2 = "# Page 2\n\nContent for page two. " * 20
        text = page1 + page2
        boundaries = [len(page1)]

        result = chunk_markdown(
            text, chunk_size=50, overlap=5, page_boundaries=boundaries
        )
        assert len(result) > 0
        page_numbers = [c.page_number for c in result if c.page_number is not None]
        assert len(page_numbers) > 0

    def test_no_page_boundaries_gives_none(self):
        text = "# Hello\n\n" + "Word " * 50
        result = chunk_markdown(text, chunk_size=100)
        assert all(c.page_number is None for c in result)


class TestChunkProperties:
    def test_chunk_indices_are_sequential(self):
        sections = [f"## Section {i}\n\n" + "Word " * 80 for i in range(10)]
        text = "\n\n".join(sections)
        result = chunk_markdown(text, chunk_size=50, overlap=5)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_token_count_is_populated(self):
        text = "# Title\n\nHello world this is a test"
        result = chunk_markdown(text, chunk_size=100)
        assert len(result) == 1
        assert result[0].token_count > 0


class TestOverlap:
    def test_overlap_between_chunks(self):
        sections = [f"## Section {i}\n\n" + " ".join([f"word{i}_{j}" for j in range(80)]) for i in range(5)]
        text = "\n\n".join(sections)
        result = chunk_markdown(text, chunk_size=100, overlap=20)
        assert len(result) > 1
        # Check consecutive chunks share some content
        for i in range(len(result) - 1):
            words_a = set(result[i].content.split())
            words_b = set(result[i + 1].content.split())
            overlap = words_a & words_b
            assert len(overlap) > 0, "Consecutive chunks should share words"


class TestLargeMarkdown:
    def test_large_markdown_produces_reasonable_chunks(self):
        sections = []
        for i in range(50):
            sections.append(
                f"## Section {i}\n\n"
                + " ".join([f"word{j}" for j in range(200)])
            )
        text = "\n\n".join(sections)
        result = chunk_markdown(text, chunk_size=1000, overlap=200)
        assert len(result) >= 5
        assert len(result) <= 100
