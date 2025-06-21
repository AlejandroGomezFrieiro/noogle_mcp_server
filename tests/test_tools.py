# tests/test_tools.py
import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup, NavigableString, Tag
import httpx

# Adjust the import path based on your project structure
# Assuming tests/ is at the same level as nix_docs_server/
from noogle_mcp_server.tools import (
    parse_paragraph,
    parse_list_item,
    NoogleInput,
    NoogleFunctionDoc,
    _fetch_page_soup,
    _parse_noogle_html,
    query_nix_docs,
)
from fastmcp.exceptions import ResourceError


@pytest.fixture
def mock_context():
    """Fixture for a mock FastMCP Context object."""
    ctx = AsyncMock()
    ctx.report_progress = AsyncMock()
    ctx.info = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


# --- Test parse_paragraph and parse_list_item ---


@pytest.mark.parametrize(
    "html_input, expected_markdown",
    [
        ("<p>Hello world.</p>", "Hello world."),
        (r'<p>This is a <a href="#link">link</a>.</p>', "This is a [link](#link)."),
        (
            "<p>Bold <strong>text</strong> and <b>more</b>.</p>",
            "Bold **text** and **more**.",
        ),
        (
            "<p>Emphasis <em>text</em> and <i>more</i>.</p>",
            "Emphasis *text* and *more*.",
        ),
        ("<p>Code: <code>nix-shell</code>.</p>", "Code: `nix-shell`."),
        (
            '<p>Mixed: <strong>bold</strong>, <em>italic</em>, <a href="/a">link</a>, <code>code</code>.</p>',
            "Mixed: **bold**, *italic*, [link](/a), `code`.",
        ),
        ("<p>  Leading and trailing spaces.  </p>", "Leading and trailing spaces."),
        ("<p>Text with   multiple    spaces.</p>", "Text with multiple spaces."),
        ("<p></p>", ""),
        (
            "<div>Only text inside</div>",
            "Only text inside",
        ),  # Test with non-<p> tag, still parses content
    ],
)
def test_parse_paragraph(html_input, expected_markdown):
    """Tests parse_paragraph with various HTML inputs."""
    soup = BeautifulSoup(html_input, "html.parser")
    element = soup.find()  # Get the first tag
    assert parse_paragraph(element) == expected_markdown


@pytest.mark.parametrize(
    "html_input, expected_markdown",
    [
        ("<li>Hello world.</li>", "Hello world."),
        (
            '<li>This is a <a href="#link">list link</a>.</li>',
            "This is a [list link](#link).",
        ),
        ("<li>Bold <strong>item</strong>.</li>", "Bold **item**."),
        ("<li>Code: <code>nix-build</code>.</li>", "Code: `nix-build`."),
        (
            '<li> Mixed: <strong>a</strong> <em>b</em> <a href="/c">c</a> <code>d</code> </li>',
            "Mixed: **a** *b* [c](/c) `d`",
        ),
        ("<li></li>", ""),
    ],
)
def test_parse_list_item(html_input, expected_markdown):
    """Tests parse_list_item with various HTML inputs."""
    soup = BeautifulSoup(html_input, "html.parser")
    element = soup.find("li")
    assert parse_list_item(element) == expected_markdown


# --- Test NoogleFunctionDoc.to_markdown ---


def test_noogle_function_doc_to_markdown_full():
    """Tests NoogleFunctionDoc.to_markdown with all fields populated."""
    doc = NoogleFunctionDoc(
        title="builtins.trace",
        description="Emits a debug message and returns the second argument.",
        inputs=[
            NoogleInput(name="message", description="The string message to emit."),
            NoogleInput(name="value", description="The value to return."),
        ],
        type_signature="a -> b -> b",
        examples=[
            'builtins.trace "Debugging foo" 123',
            'builtins.trace (builtins.toJSON { foo = "bar"; }) true;',
        ],
        aliases=["trace"],
    )
    expected_markdown = """# builtins.trace
Emits a debug message and returns the second argument.

## Inputs
message: The string message to emit.
value: The value to return.

## Type

```nix
a -> b -> b
```

## Examples

```nix
builtins.trace "Debugging foo" 123
```

```nix
builtins.trace (builtins.toJSON { foo = "bar"; }) true;
```

## Aliases

- `trace`"""
    assert doc.to_markdown().strip() == expected_markdown.strip()


def test_noogle_function_doc_to_markdown_minimal():
    """Tests NoogleFunctionDoc.to_markdown with only a title."""
    doc = NoogleFunctionDoc(title="builtins.add")
    expected_markdown = "# builtins.add"
    assert doc.to_markdown().strip() == expected_markdown.strip()


def test_noogle_function_doc_to_markdown_missing_sections():
    """Tests NoogleFunctionDoc.to_markdown with some sections missing."""
    doc = NoogleFunctionDoc(
        title="builtins.fetchUrl",
        description="Fetches a URL.",
        examples=['builtins.fetchUrl "https://example.com/file.tar.gz"'],
    )
    expected_markdown = """# builtins.fetchUrl
Fetches a URL.

## Examples

```nix
builtins.fetchUrl "https://example.com/file.tar.gz"
```"""
    assert doc.to_markdown().strip() == expected_markdown.strip()


# --- Test _fetch_page_soup ---


@pytest.mark.asyncio
async def test_fetch_page_soup_success(mock_context):
    """Tests successful fetching of a page and parsing into BeautifulSoup."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><h1>Test Page</h1></body></html>"
    mock_response.raise_for_status = Mock()  # No op, success

    with patch("httpx.AsyncClient") as MockAsyncClient:
        MockAsyncClient.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        soup = await _fetch_page_soup("http://example.com", mock_context)

        assert isinstance(soup, BeautifulSoup)
        assert soup.find("h1").get_text() == "Test Page"
        mock_context.report_progress.assert_any_call(
            progress=10, total=100, message="Fetching documentation..."
        )
        mock_context.report_progress.assert_any_call(
            progress=70, total=100, message="Processing response..."
        )
        mock_response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_page_soup_http_error(mock_context):
    """Tests _fetch_page_soup handling of HTTPStatusError."""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError(
            "404 Not Found",
            request=httpx.Request("GET", "http://example.com"),
            response=mock_response,
        )
    )

    with patch("httpx.AsyncClient") as MockAsyncClient:
        MockAsyncClient.return_value.__aenter__.return_value.get.return_value = (
            mock_response
        )

        with pytest.raises(
            ResourceError, match="Failed to fetch documentation. Status: 404"
        ):
            await _fetch_page_soup("http://example.com", mock_context)

        mock_context.error.assert_called_once()
        assert "HTTP error occurred" in mock_context.error.call_args[0][0]
        mock_context.report_progress.assert_any_call(
            progress=10, total=100, message="Fetching documentation..."
        )


@pytest.mark.asyncio
async def test_fetch_page_soup_network_error(mock_context):
    """Tests _fetch_page_soup handling of httpx.RequestError."""
    with patch("httpx.AsyncClient") as MockAsyncClient:
        MockAsyncClient.return_value.__aenter__.return_value.get.side_effect = (
            httpx.RequestError(
                "Network issue", request=httpx.Request("GET", "http://example.com")
            )
        )

        with pytest.raises(
            ResourceError, match="Network issue while connecting to noogle.dev."
        ):
            await _fetch_page_soup("http://example.com", mock_context)

        mock_context.error.assert_called_once()
        assert "Network error occurred" in mock_context.error.call_args[0][0]
        mock_context.report_progress.assert_any_call(
            progress=10, total=100, message="Fetching documentation..."
        )


# --- Test _parse_noogle_html ---


def get_full_doc_html():
    """Helper to return a full HTML string mimicking a Noogle.dev function page."""
    file_path = "./tests/data/example.html"  # Assuming the tests directory is relative to the current working directory
    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return BeautifulSoup(html_content, "html.parser")


def get_html_with_no_main_container():
    """Helper to return HTML without the main documentation container."""
    return "<html><body><div>Some other content</div></body></html>"


def get_html_minimal_doc():
    """Helper to return HTML for a minimal function documentation."""
    return """
    <html><body>
        <div class="container">
            <div class="flex items-center space-x-2 text-xl font-bold">
                lib.minimalFunction
            </div>
            <p>This is a minimal description.</p>
        </div>
    </body></html>
    """


def test_parse_noogle_html_full_doc():
    """Tests _parse_noogle_html with a complete documentation HTML structure."""
    soup = get_full_doc_html()
    doc = _parse_noogle_html(soup, "lib.intersectLists")

    assert doc.title == "lib.intersectLists"
    assert (
        doc.description
        == """Intersects list 'list1' and another list (list2).
O(nm) complexity."""
    )
    assert len(doc.inputs) == 2
    assert doc.inputs[0].name == "list1"
    assert doc.inputs[0].description == "First list"
    assert doc.inputs[1].name == "list2"
    assert doc.inputs[1].description == "Second list"
    assert doc.type_signature is None
    # assert doc.type_signature.strip() == "[string] -> set -> a -> bool -> a"
    assert len(doc.examples) == 1
    assert "intersectLists [ 1 2 3 ] [ 6 3 2 ]\n=> [ 3 2 ]" in doc.examples[0]
    assert len(doc.aliases) == 1
    assert "lib.lists.intersectLists" in doc.aliases


def test_parse_noogle_html_missing_sections():
    """Tests _parse_noogle_html when some sections are absent from HTML."""
    html = """
    <html><body>
        <div class="container">
            <div class="flex items-center space-x-2 text-xl font-bold">
                lib.simpleFunc
            </div>
            <p>A function with only a description.</p>
            <h3>Examples</h3>
            <pre>
lib.simpleFunc 123
</pre>
        </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    doc = _parse_noogle_html(soup, "lib.simpleFunc")

    assert doc.title == "lib.simpleFunc"
    assert doc.description == "A function with only a description."
    assert doc.inputs == []
    assert doc.type_signature is None
    assert len(doc.examples) == 1
    assert "lib.simpleFunc 123" in doc.examples[0]
    assert doc.aliases == []


def test_parse_noogle_html_no_main_container():
    """Tests _parse_noogle_html when the main container is missing."""
    soup = BeautifulSoup(get_html_with_no_main_container(), "html.parser")
    doc = _parse_noogle_html(soup, "some.query")
    assert doc.title == "some.query"
    assert doc.description is None
    assert doc.inputs == []
    assert doc.type_signature is None
    assert doc.examples == []
    assert doc.aliases == []


def test_parse_noogle_html_description_edge_cases():
    """Tests _parse_noogle_html's specific handling of description paragraph."""
    # Description followed by an h3 (no intervening complex divs)
    html1 = """
    <html><body><div class="container">
        <div class="flex items-center space-x-2 text-xl font-bold">Title</div>
        <p>This is the description.</p>
        <h3>Inputs</h3>
    </div></body></html>"""
    soup1 = BeautifulSoup(html1, "html.parser")
    doc1 = _parse_noogle_html(soup1, "Title")
    assert doc1.description == "This is the description."

    # Description not a direct child
    html2 = """
    <html><body><div class="container">
        <div class="flex items-center space-x-2 text-xl font-bold">Title</div>
        <div><p>This is not a direct child description.</p></div>
        <h3>Inputs</h3>
    </div></body></html>"""
    soup2 = BeautifulSoup(html2, "html.parser")
    doc2 = _parse_noogle_html(soup2, "Title")
    assert (
        doc2.description is None
    )  # Should not pick this up as it's not a direct child p


# --- Test query_nix_docs ---

# @pytest.mark.asyncio
# @patch('nix_docs_server.tools._fetch_page_soup')
# @patch('nix_docs_server.tools._parse_noogle_html')
# async def test_query_nix_docs_success(mock_parse_noogle_html, mock_fetch_page_soup, mock_context):
#     """Tests successful query_nix_docs call with full documentation."""
#     mock_soup = BeautifulSoup(get_full_doc_html(), 'html.parser')
#     mock_fetch_page_soup.return_value = mock_soup
#
#     # Create a NoogleFunctionDoc that _parse_noogle_html would return from the full doc html
#     parsed_doc = NoogleFunctionDoc(
#         title="lib.attrByPath",
#         description="Looks up an attribute at a given path in an attribute set. If **optional** is true and the attribute does not exist, it returns the `default` value.",
#         inputs=[
#             NoogleInput(name="path", description="A list of strings representing the attribute path."),
#             NoogleInput(name="attrSet", description="The attribute set to lookup in."),
#             NoogleInput(name="default", description="The value to return if the attribute is not found and `optional` is true."),
#             NoogleInput(name="optional", description="If true, no error is thrown if the attribute is not found.")
#         ],
#         type_signature="[string] -> set -> a -> bool -> a",
#         examples=[
#             'lib.attrByPath [ "a" "b" ] { a.b = 1; } null false',
#             'lib.attrByPath [ "x" ] { } "defaultVal" true'
#         ],
#         aliases=["attrByPath", "lib.getAttrFromPath"]
#     )
#     mock_parse_noogle_html.return_value = parsed_doc
#
#     query = "lib.attrByPath"
#     result = await query_nix_docs(query, mock_context)
#
#     mock_fetch_page_soup.assert_awaited_once_with(f"https://noogle.dev/f/{query.replace('.', '/')}", mock_context)
#     mock_parse_noogle_html.assert_called_once_with(mock_soup, query)
#     mock_context.info.assert_any_call(f"Attempting to query Nix documentation for: '{query}' from https://noogle.dev/f/lib/attrByPath")
#     mock_context.info.assert_any_call(f"Successfully retrieved content for '{query}'.")
#     mock_context.report_progress.assert_called_with(progress=100, total=100, message="Done.")
#     assert result == parsed_doc.to_markdown()
#
# @pytest.mark.asyncio
# @patch('nix_docs_server.tools._fetch_page_soup')
# @patch('nix_docs_server.tools._parse_noogle_html')
# async def test_query_nix_docs_minimal_content_error(mock_parse_noogle_html, mock_fetch_page_soup, mock_context):
#     """Tests query_nix_docs raising ResourceError for minimal extracted content."""
#     mock_soup = BeautifulSoup(get_html_minimal_doc(), 'html.parser')
#     mock_fetch_page_soup.return_value = mock_soup
#
#     # Return a doc with just title and a short description, triggering the minimal content check
#     parsed_doc = NoogleFunctionDoc(title="lib.minimalFunction", description="This is a minimal description.")
#     mock_parse_noogle_html.return_value = parsed_doc
#
#     query = "lib.minimalFunction"
#     with pytest.raises(ResourceError, match=f"No detailed content found for '{query}'"):
#         await query_nix_docs(query, mock_context)
#
#     mock_context.info.assert_any_call(f"No specific documentation content extracted for '{query}'. Attempting fallback or raising error.")
#     mock_context.error.assert_not_called() # No error message for this specific failure as it's a known 'no content'
#     mock_context.report_progress.assert_not_called() # Not called if error is raised before final progress
#
# @pytest.mark.asyncio
# @patch('nix_docs_server.tools._fetch_page_soup')
# @patch('nix_docs_server.tools._parse_noogle_html')
# async def test_query_nix_docs_fallback_to_raw_html_body(mock_parse_noogle_html, mock_fetch_page_soup, mock_context):
#     """Tests query_nix_docs falling back to returning raw HTML body for unparsed content."""
#     html_content = "<html><body><h1>Search Result for builtins.foo</h1><p>This is a very long text to ensure the raw body is returned and truncated.</p>" + ("long text " * 100) + "</body></html>"
#     mock_soup = BeautifulSoup(html_content, 'html.parser')
#     mock_fetch_page_soup.return_value = mock_soup
#
#     # Return a doc with just title, making the content check fail
#     parsed_doc = NoogleFunctionDoc(title="builtins.foo")
#     mock_parse_noogle_html.return_value = parsed_doc
#
#     query = "builtins.foo"
#     result = await query_nix_docs(query, mock_context)
#
#     mock_context.info.assert_any_call(f"No specific documentation content extracted for '{query}'. Attempting fallback or raising error.")
#     assert result.startswith("```\nSearch Result for builtins.foo\nThis is a very long text to ensure the raw body is returned and truncated.")
#     assert "..." in result
#     assert len(result) < 1050 + 10 # Check for truncation, 1000 chars + markdown overhead
#
# @pytest.mark.asyncio
# @patch('nix_docs_server.tools._fetch_page_soup')
# async def test_query_nix_docs_fetch_error(mock_fetch_page_soup, mock_context):
#     """Tests query_nix_docs propagating ResourceError from _fetch_page_soup."""
#     mock_fetch_page_soup.side_effect = ResourceError("Failed to fetch.")
#
#     query = "builtins.fail"
#     with pytest.raises(ResourceError, match="Failed to fetch."):
#         await query_nix_docs(query, mock_context)
#
#     mock_context.error.assert_not_called() # The ResourceError is re-raised, no new error message
#     mock_context.info.assert_any_call(f"Attempting to query Nix documentation for: '{query}' from https://noogle.dev/f/builtins/fail")
#
# @pytest.mark.asyncio
# @patch('nix_docs_server.tools._fetch_page_soup')
# @patch('nix_docs_server.tools._parse_noogle_html')
# async def test_query_nix_docs_unexpected_exception(mock_parse_noogle_html, mock_fetch_page_soup, mock_context):
#     """Tests query_nix_docs handling unexpected exceptions during parsing."""
#     mock_fetch_page_soup.return_value = BeautifulSoup("<html><body><div class=\"container\"></div></body></html>", 'html.parser')
#     mock_parse_noogle_html.side_effect = Exception("Parsing error!")
#
#     query = "builtins.error"
#     with pytest.raises(ResourceError, match="An unexpected issue occurred while querying Nix docs."):
#         await query_nix_docs(query, mock_context)
#
#     mock_context.error.assert_called_once()
#     assert "An unexpected error occurred while fetching docs for 'builtins.error': Parsing error!" in mock_context.error.call_args[0][0]
