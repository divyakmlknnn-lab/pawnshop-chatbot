import unittest
from unittest.mock import patch

import llm_chat
from gemini_text_html import gemini_text_to_html, looks_like_html
from intent import UNKNOWN, IntentClassification


class GeminiTextHtmlTests(unittest.TestCase):
    def test_bold_markdown_renders_without_markdown_symbols(self):
        html = gemini_text_to_html("This is **bold** text.")
        self.assertIn("<strong>bold</strong>", html)
        self.assertNotIn("**", html)

    def test_italic_markdown_renders(self):
        html = gemini_text_to_html("This is *italic* text.")
        self.assertIn("<em>italic</em>", html)
        self.assertNotIn("*italic*", html)

    def test_unordered_list_renders(self):
        html = gemini_text_to_html("- First item\n- Second item")
        self.assertIn("<ul>", html)
        self.assertIn("<li>First item</li>", html)
        self.assertIn("<li>Second item</li>", html)
        self.assertNotIn("- First item", html)

    def test_ordered_list_renders(self):
        html = gemini_text_to_html("1. First\n2. Second")
        self.assertIn("<ol>", html)
        self.assertIn("<li>First</li>", html)
        self.assertIn("<li>Second</li>", html)

    def test_table_renders(self):
        markdown = (
            "| Name | Balance |\n"
            "| --- | ---: |\n"
            "| Asha | $100.00 |\n"
        )
        html = gemini_text_to_html(markdown)
        self.assertIn("<table>", html)
        self.assertIn("<th>Name</th>", html)
        self.assertIn("<td>Asha</td>", html)
        self.assertNotIn("| Name |", html)

    def test_paragraphs_render(self):
        html = gemini_text_to_html("First paragraph.\n\nSecond paragraph.")
        self.assertIn("<p>First paragraph.</p>", html)
        self.assertIn("<p>Second paragraph.</p>", html)

    def test_existing_html_is_not_escaped(self):
        source = "<p><strong>Ready</strong> for review.</p>"
        self.assertTrue(looks_like_html(source))
        html = gemini_text_to_html(source)
        self.assertIn("<strong>Ready</strong>", html)
        self.assertNotIn("&lt;strong&gt;", html)

    def test_unsafe_html_is_sanitized(self):
        html = gemini_text_to_html('<p>Safe</p><script>alert("x")</script>')
        self.assertIn("<p>Safe</p>", html)
        self.assertNotIn("<script>", html)

    def test_markdown_link_renders_safely(self):
        html = gemini_text_to_html("See [docs](https://example.com/guide).")
        self.assertIn('href="https://example.com/guide"', html)
        self.assertNotIn("[docs]", html)

    def test_pure_html_with_existing_lists_unchanged(self):
        source = "<p>Intro</p><ul><li><strong>Search</strong> for customers</li></ul>"
        html = gemini_text_to_html(source)
        self.assertIn("<ul>", html)
        self.assertIn("<li>", html)
        self.assertIn("<strong>Search</strong>", html)
        self.assertNotIn("* ", html)

    def test_hybrid_html_and_markdown_list_renders(self):
        source = (
            "<p>I can help with a variety of tasks related to pawnshop and banking operations. "
            "Here are some examples of what I can do:</p>"
            "<p><strong>Customer Information:</strong>\n"
            "*   Search for customers by name.\n"
            "*   Get details about customer accounts, loans, payments, and collateral.</p>"
            "<p><strong>Loan and Payment Tracking:</strong>\n"
            "*   List overdue customers and payments.\n"
            "*   Identify customers with payments due soon, today, or this week.</p>"
        )
        html = gemini_text_to_html(source)
        self.assertIn("<ul>", html)
        self.assertIn("Search for customers by name.", html)
        self.assertIn("Get details about customer accounts, loans, payments, and collateral.", html)
        self.assertIn("List overdue customers and payments.", html)
        self.assertIn("<strong>Customer Information:</strong>", html)
        self.assertNotIn("*   Search for customers", html)
        self.assertNotIn("*   List overdue customers", html)

    def test_hybrid_html_with_dash_list_renders(self):
        source = "<p><strong>Options:</strong>\n- Search for customers\n- List customers</p>"
        html = gemini_text_to_html(source)
        self.assertIn("<ul>", html)
        self.assertIn("Search for customers", html)
        self.assertIn("List customers", html)
        self.assertNotIn("- Search for customers", html)

    def test_heading_markdown_renders(self):
        html = gemini_text_to_html("## Customer tools\n\nUse these features.")
        self.assertIn("<h2>", html)
        self.assertIn("Customer tools", html)
        self.assertNotIn("##", html)

    def test_empty_input_renders_empty_message(self):
        html = gemini_text_to_html("")
        self.assertIn('class="empty-message"', html)


class TextToHtmlResponseTests(unittest.TestCase):
    def _classification(self) -> IntentClassification:
        return IntentClassification(intent=UNKNOWN, confidence=0.0)

    def test_text_to_html_response_converts_markdown_without_visible_markers(self):
        text = (
            "I can:\n\n"
            "*   **Search for customers** by name.\n"
            "*   **List overdue customers**."
        )
        result = llm_chat._text_to_html_response(
            text,
            "history",
            self._classification(),
            [],
            [],
        )

        self.assertEqual(result["format"], "html")
        self.assertEqual(result["history_text"], "history")
        self.assertIn("<ul>", result["reply"])
        self.assertIn("<strong>Search for customers</strong>", result["reply"])
        self.assertNotIn("**", result["reply"])
        self.assertNotIn("*   Search for customers", result["reply"])

    def test_text_to_html_response_empty_input(self):
        result = llm_chat._text_to_html_response(
            "",
            "history",
            self._classification(),
            [],
            [],
        )

        self.assertIn("empty-message", result["reply"])

    def test_text_to_html_response_fallback_on_conversion_error(self):
        with patch("llm_chat.gemini_text_to_html", side_effect=RuntimeError("boom")):
            result = llm_chat._text_to_html_response(
                "Hello **world**",
                "history",
                self._classification(),
                [],
                [],
            )

        self.assertEqual(result["format"], "html")
        self.assertIn("Hello **world**", result["reply"])
        self.assertNotIn("<strong>", result["reply"])


if __name__ == "__main__":
    unittest.main()
