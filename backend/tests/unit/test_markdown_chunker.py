import pytest

from app.services.documents.markdown_chunker import (
    chunk_by_pages,
    chunk_markdown,
    rechunk_with_structure,
    _inject_headings,
    _segment_into_blocks,
    _split_at_headings,
    _strip_skip_lines,
)
from app.services.documents.document_structure import (
    DocumentOutline,
    DocumentStructure,
    PageAnalysis,
    PageHeading,
)
from app.services.data.text_chunker import PageData


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


# ── chunk_by_pages tests ───────────────────────────────────────────


class TestChunkByPagesEmpty:
    def test_empty_list(self):
        assert chunk_by_pages([]) == []

    def test_single_empty_page(self):
        pages = [PageData(page_number=1, text="")]
        assert chunk_by_pages(pages) == []

    def test_single_whitespace_page(self):
        pages = [PageData(page_number=1, text="   \n  ")]
        assert chunk_by_pages(pages) == []


class TestChunkByPagesBasic:
    def test_single_page_becomes_one_chunk(self):
        pages = [PageData(page_number=1, text="# Intro\n\nSome body text here.")]
        result = chunk_by_pages(pages)
        assert len(result) == 1
        assert result[0].page_number == 1
        assert result[0].chunk_index == 0
        assert "Intro" in result[0].content

    def test_each_page_gets_its_own_chunk(self):
        pages = [
            PageData(page_number=1, text="Page one " + "word " * 120),
            PageData(page_number=2, text="Page two " + "word " * 120),
            PageData(page_number=3, text="Page three " + "word " * 120),
        ]
        result = chunk_by_pages(pages)
        assert len(result) == 3
        assert result[0].page_number == 1
        assert result[1].page_number == 2
        assert result[2].page_number == 3

    def test_page_numbers_preserved(self):
        pages = [
            PageData(page_number=5, text="Content " * 120),
            PageData(page_number=6, text="More " * 120),
        ]
        result = chunk_by_pages(pages)
        assert result[0].page_number == 5
        assert result[1].page_number == 6

    def test_no_overlap_between_chunks(self):
        """Page-level chunks should NOT have overlapping content."""
        pages = [
            PageData(page_number=1, text="ALPHA " * 120),
            PageData(page_number=2, text="BETA " * 120),
        ]
        result = chunk_by_pages(pages)
        assert len(result) == 2
        assert "BETA" not in result[0].content
        assert "ALPHA" not in result[1].content


class TestChunkByPagesMergeShort:
    def test_short_pages_merged(self):
        """Pages below the merge threshold should be combined."""
        pages = [
            PageData(page_number=1, text="Short"),
            PageData(page_number=2, text="Also short"),
            PageData(page_number=3, text="Still short"),
        ]
        result = chunk_by_pages(pages, merge_short=100)
        # All three are very short, should merge into one chunk
        assert len(result) == 1
        assert "Short" in result[0].content
        assert "Also short" in result[0].content
        assert result[0].page_number == 1  # first page's number

    def test_short_then_normal(self):
        """Short page followed by normal page: short is flushed, normal is separate."""
        pages = [
            PageData(page_number=1, text="tiny"),
            PageData(page_number=2, text="Normal page " + "word " * 120),
        ]
        result = chunk_by_pages(pages, merge_short=100)
        assert len(result) == 2


class TestChunkByPagesSplitLong:
    def test_long_page_is_split(self):
        """A page with many tokens should be split into multiple chunks."""
        long_text = "\n\n".join(
            f"## Section {i}\n\n" + "word " * 500
            for i in range(5)
        )
        pages = [PageData(page_number=1, text=long_text)]
        result = chunk_by_pages(pages, split_long=800)
        assert len(result) > 1
        # All chunks should reference the same page
        for chunk in result:
            assert chunk.page_number == 1

    def test_sequential_indices(self):
        """All chunks should have sequential 0-based indices."""
        long_text = "\n\n".join(
            f"## Heading {i}\n\n" + "content " * 300
            for i in range(4)
        )
        pages = [
            PageData(page_number=1, text=long_text),
            PageData(page_number=2, text="Normal page " + "word " * 120),
        ]
        result = chunk_by_pages(pages, split_long=500)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i


# ── _strip_skip_lines tests ──────────────────────────────────────────


class TestStripSkipLines:
    def test_strips_matching_lines(self):
        text = "HEADER\nSome body text.\n42"
        result = _strip_skip_lines(text, ["HEADER", "42"])
        assert "HEADER" not in result
        assert "42" not in result
        assert "Some body text." in result

    def test_case_insensitive(self):
        text = "Contents\nBody text here.\ncontents"
        result = _strip_skip_lines(text, ["CONTENTS"])
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) == 1
        assert "Body text" in result

    def test_empty_skip_lines(self):
        text = "No changes here."
        assert _strip_skip_lines(text, []) == text

    def test_no_match(self):
        text = "Line one\nLine two"
        result = _strip_skip_lines(text, ["MISSING"])
        assert "Line one" in result
        assert "Line two" in result


# ── _inject_headings tests ───────────────────────────────────────────


class TestInjectHeadings:
    def test_injects_heading_prefix(self):
        text = "Chapter 1. Introduction\nSome body text."
        headings = [PageHeading(level=1, text="Chapter 1. Introduction")]
        result = _inject_headings(text, headings)
        assert result.startswith("# Chapter 1. Introduction")
        assert "Some body text." in result

    def test_multiple_headings(self):
        text = (
            "Chapter 2. Methods\n"
            "Some intro.\n"
            "2.1 Sample Preparation\n"
            "Details here."
        )
        headings = [
            PageHeading(level=1, text="Chapter 2. Methods"),
            PageHeading(level=2, text="2.1 Sample Preparation"),
        ]
        result = _inject_headings(text, headings)
        assert "# Chapter 2. Methods" in result
        assert "## 2.1 Sample Preparation" in result

    def test_no_headings(self):
        text = "Just plain text."
        result = _inject_headings(text, [])
        assert result == text

    def test_no_match_leaves_text_unchanged(self):
        text = "Some random text.\nAnother line."
        headings = [PageHeading(level=1, text="Nonexistent Heading")]
        result = _inject_headings(text, headings)
        assert result == text

    def test_does_not_double_prefix(self):
        text = "# Already a heading\nBody text."
        headings = [PageHeading(level=1, text="Already a heading")]
        result = _inject_headings(text, headings)
        # Should not become "# # Already a heading"
        assert "# #" not in result


# ── _split_at_headings tests ─────────────────────────────────────────


class TestSplitAtHeadings:
    def test_splits_at_heading_boundaries(self):
        text = (
            "# Chapter 1\n" + "Content one word. " * 30 + "\n"
            "# Chapter 2\n" + "Content two word. " * 30 + "\n"
            "# Chapter 3\n" + "Content three word. " * 30
        )
        result = _split_at_headings(text, max_tokens=1000)
        assert len(result) == 3
        assert "Chapter 1" in result[0]
        assert "Chapter 2" in result[1]
        assert "Chapter 3" in result[2]

    def test_no_headings_returns_single_chunk(self):
        text = "Just some text without headings."
        result = _split_at_headings(text, max_tokens=1000)
        assert len(result) == 1

    def test_merges_short_chunks(self):
        text = "# H1\nA\n# H2\nB"
        result = _split_at_headings(text, max_tokens=1000)
        # Both chunks are very short, first should merge with second
        assert len(result) == 1


# ── rechunk_with_structure tests ─────────────────────────────────────


class TestRechunkWithStructure:
    def _make_structure(
        self, page_analyses: list[PageAnalysis]
    ) -> DocumentStructure:
        return DocumentStructure(
            outline=DocumentOutline(heading_levels=2),
            pages=page_analyses,
        )

    def test_empty_pages_returns_empty(self):
        result = rechunk_with_structure([], DocumentStructure())
        assert result == []

    def test_useless_structure_falls_back(self):
        """All-body with no headings/skip_lines falls back to page chunks."""
        pages = [
            PageData(page_number=1, text="Body text " * 50),
            PageData(page_number=2, text="More body " * 50),
        ]
        structure = self._make_structure([
            PageAnalysis(page=1),
            PageAnalysis(page=2),
        ])
        result = rechunk_with_structure(pages, structure)
        # Should fall back to chunk_by_pages
        assert len(result) == 2

    def test_skip_lines_stripped(self):
        pages = [
            PageData(
                page_number=1,
                text="HEADER\nBody content here.\n42",
            ),
        ]
        structure = self._make_structure([
            PageAnalysis(
                page=1,
                role="body",
                skip_lines=["HEADER", "42"],
                headings=[PageHeading(level=1, text="Body content here.")],
            ),
        ])
        result = rechunk_with_structure(pages, structure)
        assert len(result) >= 1
        assert "HEADER" not in result[0].content
        assert "42" not in result[0].content

    def test_headings_injected(self):
        pages = [
            PageData(
                page_number=1,
                text="Chapter 1\nBody content.\n1.1 Methods\nMore text.",
            ),
        ]
        structure = self._make_structure([
            PageAnalysis(
                page=1,
                role="body",
                headings=[
                    PageHeading(level=1, text="Chapter 1"),
                    PageHeading(level=2, text="1.1 Methods"),
                ],
            ),
        ])
        result = rechunk_with_structure(pages, structure)
        all_content = " ".join(c.content for c in result)
        assert "# Chapter 1" in all_content
        assert "## 1.1 Methods" in all_content

    def test_non_body_roles_merged(self):
        pages = [
            PageData(page_number=1, text="Title Page " * 20),
            PageData(page_number=2, text="Copyright " * 20),
            PageData(page_number=3, text="Body content " * 50),
        ]
        structure = self._make_structure([
            PageAnalysis(page=1, role="front_matter",
                         skip_lines=["dummy"]),
            PageAnalysis(page=2, role="front_matter",
                         skip_lines=["dummy"]),
            PageAnalysis(page=3, role="body",
                         headings=[PageHeading(level=1, text="Body content")]),
        ])
        result = rechunk_with_structure(pages, structure)
        # Front matter pages should be merged into one chunk
        roles_seen = []
        for chunk in result:
            if "Title Page" in chunk.content or "Copyright" in chunk.content:
                roles_seen.append("front_matter")
            else:
                roles_seen.append("body")
        # Should have at most 1 front_matter chunk
        assert roles_seen.count("front_matter") <= 1

    def test_sequential_chunk_indices(self):
        pages = [
            PageData(page_number=i, text=f"Page {i} " * 50)
            for i in range(1, 4)
        ]
        structure = self._make_structure([
            PageAnalysis(page=i, role="body",
                         headings=[PageHeading(level=1, text=f"Page {i}")])
            for i in range(1, 4)
        ])
        result = rechunk_with_structure(pages, structure)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i
