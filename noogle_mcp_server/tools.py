import httpx
from urllib.parse import quote_plus
from typing import Annotated, List, Optional
from pydantic import Field, BaseModel
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError
from bs4 import BeautifulSoup, NavigableString, Tag

mcp = FastMCP("Noogle server")


def _parse_inline_markdown(element: Tag) -> str:
    """Helper to parse a BeautifulSoup element's contents for inline Markdown formatting."""
    paragraph_text_parts = []
    for content in element.contents:
        if isinstance(content, NavigableString):
            paragraph_text_parts.append(str(content))
        elif content.name == "a":
            href = content.get("href", "#")
            text = content.get_text(strip=False)
            paragraph_text_parts.append(f"[{text}]({href})")
        elif content.name in ["strong", "b"]:
            paragraph_text_parts.append(f"**{content.get_text(strip=False)}**")
        elif content.name in ["em", "i"]:
            paragraph_text_parts.append(f"*{content.get_text(strip=False)}*")
        elif content.name == "code":
            paragraph_text_parts.append(f"`{content.get_text(strip=False)}`")
    # Join parts and clean up multiple spaces, then strip leading/trailing whitespace
    return " ".join("".join(paragraph_text_parts).split()).strip()


def parse_paragraph(element: Tag) -> str:
    """Helper to parse a BeautifulSoup element's contents into a Markdown paragraph.

    Args:
        element (bs4.Tag): The BeautifulSoup Tag element to parse, typically a <p> tag.

    Returns:
        str: The Markdown formatted paragraph text.
    """
    return _parse_inline_markdown(element)


def parse_list_item(element: Tag) -> str:
    """Helper to parse a BeautifulSoup <li> element's contents, typically used for aliases.

    Args:
        element (bs4.Tag): The BeautifulSoup Tag element to parse, typically an <li> tag.

    Returns:
        str: The Markdown formatted text content of the list item.
    """
    return _parse_inline_markdown(element)


class NoogleInput(BaseModel):
    name: str
    description: str


class NoogleFunctionDoc(BaseModel):
    title: str
    description: Optional[str] = None
    inputs: List[NoogleInput] = Field(default_factory=list)
    type_signature: Optional[str] = None
    examples: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Converts the structured Noogle function documentation into a Markdown string.

        Returns:
            str: The Markdown representation of the function documentation.
        """
        parts = []
        parts.append(f"# {self.title}")
        if self.description:
            parts.append(self.description)
            parts.append("")  # Blank line after description

        if self.inputs:
            parts.append("## Inputs")
            for inp in self.inputs:
                parts.append(f"{inp.name}: {inp.description}")
            parts.append("")  # Blank line after inputs section

        if self.type_signature:
            parts.append("## Type")
            parts.append("")  # Blank line after heading
            parts.append(f"```nix\n{self.type_signature.strip()}\n```")
            parts.append("")  # Blank line after code block

        if self.examples:
            parts.append("## Examples")
            parts.append("")  # Blank line after heading
            for i, example in enumerate(self.examples):
                parts.append(f"```nix\n{example.strip()}\n```")
                if i < len(self.examples) - 1:  # Add blank line between examples
                    parts.append("")
            parts.append("")  # Add a blank line after the whole examples section

        if self.aliases:
            parts.append("## Aliases")
            parts.append("")  # Blank line after heading
            for alias in self.aliases:
                # Check if the alias already contains markdown backticks
                if alias.startswith("`") and alias.endswith("`") and len(alias) > 2:
                    parts.append(f"- {alias}")
                else:
                    parts.append(f"- `{alias}`")
            parts.append("")  # Blank line after aliases section

        return "\n".join(parts).strip()


async def _fetch_page_soup(search_url: str, ctx: Context) -> BeautifulSoup:
    """Fetches the HTML content from the given URL and parses it into a BeautifulSoup object.

    Args:
        search_url (str): The URL to fetch.
        ctx (Context): The FastMCP context object for progress reporting.

    Returns:
        BeautifulSoup: A BeautifulSoup object representing the parsed HTML content.

    Raises:
        ResourceError: If there's an HTTP error, network issue, or the response is empty.
    """
    await ctx.report_progress(
        progress=10, total=100, message="Fetching documentation..."
    )
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(search_url, follow_redirects=True, timeout=10)
            response.raise_for_status()
            await ctx.report_progress(
                progress=70, total=100, message="Processing response..."
            )
            return BeautifulSoup(response.text, "html.parser")
    except httpx.HTTPStatusError as e:
        await ctx.error(
            f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        )
        raise ResourceError(
            f"Failed to fetch documentation. Status: {e.response.status_code}"
        )
    except httpx.RequestError as e:
        await ctx.error(f"Network error occurred: {e}")
        raise ResourceError(f"Network issue while connecting to noogle.dev.")


def _parse_noogle_html(soup: BeautifulSoup, query: str) -> NoogleFunctionDoc:
    """
    Parses a BeautifulSoup object representing a Noogle HTML page to extract function documentation.

    Args:
        soup (BeautifulSoup): The BeautifulSoup object of the HTML page.
        query (str): The original query string, used as a fallback for the title.

    Returns:
        NoogleFunctionDoc: A structured object containing the parsed function documentation.
    """
    title: Optional[str] = query  # Initialize with query as a fallback
    description: Optional[str] = None
    inputs: List[NoogleInput] = []
    type_signature: Optional[str] = None
    examples: List[str] = []
    aliases: List[str] = []

    # Determine the effective root for parsing based on known Noogle structure or simpler test structures
    effective_root = None
    main_tag = soup.find("main", attrs={"data-pagefind-body": "true"})
    if main_tag:
        effective_root = main_tag
    else:
        # Fallback for simpler test cases that might use a 'container' div
        effective_root = soup.find("div", class_="container")
        if not effective_root:
            # Final fallback to body or the entire soup if no specific container is found
            effective_root = soup.body if soup.body else soup

    if not effective_root:
        # This case should ideally not be reached with the fallbacks above, but as a safeguard
        return NoogleFunctionDoc(
            title=query, description="Could not find a parsable root element."
        )

    # 1. Parse Title
    # Try to find the H1 tag with the specific ID first (for full Noogle docs)
    title_id = query.replace(" ", "")
    h1_tag = effective_root.find("h1", id=title_id)
    if h1_tag:
        title = h1_tag.get_text(separator="").strip()
    else:
        # For simplified HTML, title might be in a div with specific styling
        simplified_title_div = effective_root.find(
            "div", class_="flex items-center space-x-2 text-xl font-bold"
        )
        if simplified_title_div:
            title = simplified_title_div.get_text().strip()
        # If not found, title remains the initial query fallback

    # Determine the content area where description, inputs, and examples are located
    content_area = None
    # In full noogle.dev HTML, content is typically after a specific HR tag
    content_section_start_hr = effective_root.find("hr", class_="mui-zdzcbx")
    if content_section_start_hr:
        # The content is often in the div immediately after this specific HR
        content_area = content_section_start_hr.find_next_sibling("div")
        # Check if this div is empty (like mui-13o7eu2 in example.html) and move to the next
        if (
            content_area
            and not content_area.get_text(strip=True)
            and content_area.find_next_sibling("div")
        ):
            content_area = content_area.find_next_sibling("div")
    else:
        # For simpler test cases, the content might be directly within the effective_root or a direct child
        content_area = effective_root

    if content_area:
        # 2. Parse Description
        description_parts = []
        for child in content_area.children:
            if isinstance(child, Tag):
                if child.name == "p":
                    description_parts.append(child.get_text().strip())
                # Stop collecting description when a new section heading is encountered
                elif child.name in ["h2", "h3"]:
                    break
        if description_parts:
            description = "\n".join(description_parts).strip()

        # 3. Parse Inputs
        inputs_h = content_area.find(["h2", "h3"], string="Inputs")
        if inputs_h:
            dl_tag = inputs_h.find_next_sibling("dl")
            if dl_tag:
                for dt, dd in zip(dl_tag.find_all("dt"), dl_tag.find_all("dd")):
                    input_name_tag = dt.find("code")
                    input_name = (
                        input_name_tag.get_text().strip()
                        if input_name_tag
                        else dt.get_text().strip()
                    )

                    input_description_tag = dd.find("p")
                    input_description = (
                        input_description_tag.get_text().strip()
                        if input_description_tag
                        else dd.get_text().strip()
                    )
                    inputs.append(
                        NoogleInput(name=input_name, description=input_description)
                    )

        # 4. Parse Examples
        examples_h = content_area.find(["h2", "h3"], string="Examples")
        if examples_h:
            # First, check for the typical 'div.example' wrapper
            current_sibling = examples_h.find_next_sibling()
            while current_sibling:
                if isinstance(current_sibling, Tag):
                    # if current_sibling.name == 'div' and 'example' in current_sibling.get('class', []):
                    # current_sibling.find("code", class="hlks language-nix")
                    code_block = current_sibling.find(
                        "code", class_="hljs language-nix"
                    )
                    if code_block:
                        examples.append(code_block.get_text().strip())
                    elif current_sibling.name in ["h2", "h3"]:
                        # Stop if another major H2/H3 section starts, but not the nested example H2/H3
                        if (
                            current_sibling.get_text().strip()
                            != f"{query} usage example"
                        ):
                            break
                    # Also check for direct <pre> tags as immediate siblings (for simpler test cases)
                    elif current_sibling.name == "pre":
                        examples.append(current_sibling.get_text().strip())
                        # If a direct pre is found, assume it's the only example or a specific test case, and stop.
                        break
                current_sibling = current_sibling.find_next_sibling()

    # 5. Parse Aliases (often found at the same level as content_area, or within effective_root)
    aliases_h = effective_root.find(["h2", "h3"], string="Aliases")
    if aliases_h:
        ul_tag = effective_root.find(["ul"])
        # ul_tag = aliases_h.find_next_sibling()
        if ul_tag:
            for li in ul_tag.find_all("li"):
                a_tag = li.find("a")
                if a_tag:
                    aliases.append(a_tag.get_text().strip())

    # 6. Parse Type Signature (Implementation)
    implementation_h = effective_root.find(["h2", "h3"], string="Implementation")
    if implementation_h:
        tip_div = implementation_h.find_next_sibling("div", class_="tip")
        if tip_div:
            code_block = tip_div.find("pre", class_="hljs language-nix")
            if code_block and code_block.code:
                type_signature = code_block.code.get_text().strip()
        else:
            # Fallback for direct <pre> tags after the heading (for simpler test cases)
            direct_pre = implementation_h.find_next_sibling("pre")
            if direct_pre:
                type_signature = direct_pre.get_text().strip()

    return NoogleFunctionDoc(
        title=title,
        description=description,
        inputs=inputs,
        type_signature=type_signature,
        examples=examples,
        aliases=aliases,
    )


@mcp.tool()
async def query_nix_docs(
    query: Annotated[
        str,
        Field(
            description="The search query for Nix built-in documentation (e.g., 'builtins.trace', 'nixpkgs.fetchUrl')"
        ),
    ],
    ctx: Context,
) -> str:
    """
    Queries builtin Nix documentation from noogle.dev for a given query.
    Returns the documentation content formatted as structured Markdown.
    """
    transformed_query = query.replace(".", "/")
    search_url = f"https://noogle.dev/f/{quote_plus(transformed_query)}"

    await ctx.info(
        f"Attempting to query Nix documentation for: '{query}' from {search_url}"
    )

    try:
        soup = await _fetch_page_soup(search_url, ctx)
        parsed_doc = _parse_noogle_html(soup, query)

        # Check if the parsed document contains substantial information
        is_minimal_content = not (
            parsed_doc.inputs
            or parsed_doc.type_signature
            or parsed_doc.examples
            or parsed_doc.aliases
            or parsed_doc.description
        )
        # If the description is very short and no other sections are present, it's also minimal
        if (
            parsed_doc.description
            and len(parsed_doc.description.strip()) < 50
            and is_minimal_content
        ):
            is_minimal_content = True
        elif (
            parsed_doc.description and is_minimal_content
        ):  # If description exists but no other fields
            is_minimal_content = (
                False  # Treat it as not minimal if description alone is sufficient
            )

        if is_minimal_content:
            await ctx.info(
                f"No specific documentation content extracted for '{query}'. Attempting fallback or raising error."
            )

            body_content = soup.find("body")
            if body_content:
                text = body_content.get_text(separator="\n", strip=True)
                # Compare the length of the extracted raw text to the length of the parsed title + description (if any)
                # If raw text is substantially larger, return it.
                parsed_len = len(parsed_doc.title) + (
                    len(parsed_doc.description) if parsed_doc.description else 0
                )
                if len(text) > (
                    parsed_len + 50
                ):  # Heuristic: if raw text is much longer, it might be useful
                    return f"```\n{text[:1000]}...\n```"  # Truncate large raw text for readability
                else:
                    raise ResourceError(f"No detailed content found for '{query}'.")
            else:
                raise ResourceError(
                    f"No detailed documentation found for '{query}' on noogle.dev. You might want to try a different query or check the website directly: {search_url}"
                )

        await ctx.info(f"Successfully retrieved content for '{query}'.")
        await ctx.report_progress(progress=100, total=100, message="Done.")

        return parsed_doc.to_markdown()

    except (
        ResourceError
    ):  # Re-raise ResourceError directly as it's already contextualized
        raise
    except httpx.HTTPStatusError as e:
        await ctx.error(
            f"HTTP error occurred while fetching docs for '{query}': {e.response.status_code} - {e.response.text}"
        )
        raise ResourceError(
            f"Failed to fetch documentation from noogle.dev. Status: {e.response.status_code}"
        )
    except httpx.RequestError as e:
        await ctx.error(
            f"Network error occurred while fetching docs for '{query}': {e}"
        )
        raise ResourceError(f"Network issue while connecting to noogle.dev.")
    except Exception as e:
        await ctx.error(
            f"An unexpected error occurred while fetching docs for '{query}': {e}"
        )
        raise ResourceError(f"An unexpected issue occurred while querying Nix docs.")
