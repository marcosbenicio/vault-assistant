import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

@dataclass
class Document:
    """The LangChain document shape: the text and everything about it."""
    page_content: str
    metadata: dict = field(default_factory=dict)

    def show(self, preview=400):
        """Human view of this Document at any stage: whole note, chunk
        (start appears) or retrieval hit (score appears). Only prints
        the metadata the stage actually carries."""
        meta = self.metadata

        print("=" * 72)
        print(f"Title: {meta.get('title', '?')}   Folder: [{meta.get('folder', '?')}]")
        print("=" * 72)
        print(f"source:          {meta.get('source')}")
        if "start" in meta:
            print(f"start:           {meta['start']}")
        if "score" in meta:
            print(f"score:           {meta['score']:.4f}")
        if "last_modified" in meta:
            print(f"last modified:   {meta['last_modified'][:19]}")
        if "tags" in meta:
            print(f"tags:            {', '.join(meta['tags']) or '(none)'}")

        edges = meta.get("graph_edges")
        if edges is not None:
            print(f"graph edges:     {'(none)' if not edges else ''}")
            for name, weight in sorted(edges.items(), key=lambda e: -e[1]):
                print(f"   {name} : {weight}")

        links = meta.get("external_links")
        if links is not None:
            print(f"external links:  {'(none)' if not links else ''}")
            for url in links:
                print(f"    {url}")

        print(f"\ncontent: {len(self.page_content)} chars, first {preview}:")
        print("-" * 72)
        print()
        print(self.page_content[:preview])
        print("-" * 72)


class NoteCleaner:
    """Prepares raw vault markdown (the wikilink dialect Obsidian
    popularized) for indexing.

    Every link syntax has a target, and the target decides its fate:
    notes become weighted graph edges, attachments and sizes disappear,
    external urls are stored aside, and the reader-visible words always
    stay in the text. Classification looks only at url scheme and file
    extension, never at content, so the rules work on any vault.

    clean() returns (text, graph_edges, external_links): the readable
    text, a Counter of referenced note names where each count is the
    edge weight (citing a note three times is a three times stronger
    connection), and the external urls kept out of the searchable text.
    """

    # the four syntaxes, from most specific to most generic:
    WIKILINK_EMBED = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")   # ![[target|size]]
    MARKDOWN_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")      # ![alt](file)
    WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")        # [[target|alias]]
    MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")        # [label](target)

    IMAGE_SIZE = re.compile(r"^\d+(x\d+)?$")    # alt texts like 250 or 100x145

    ATTACHMENT_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp",
        ".pdf", ".mp3", ".wav", ".ogg", ".m4a", ".flac",
        ".mp4", ".webm", ".mov", ".zip", ".canvas", ".excalidraw",
    }

    # what a target can point at:
    NOTE = "note"              # ends in .md or has no extension
    ATTACHMENT = "attachment"  # extension in ATTACHMENT_EXTENSIONS
    EXTERNAL = "external"      # starts with http:// or https://
    OTHER = "other"            # anything else: .py files, dead folders

    def clean(self, text):
        """Run every pass in order and return the three products.

        Order matters: a wikilink embed contains the image pattern, and
        an image contains the link pattern, so the most specific rule
        runs first or the generic one swallows its cases.
        """
        references, external_links = [], []
        text = self._clean_embeds(text, references)
        text = self._clean_images(text)
        text = self._clean_wikilinks(text, references)
        text = self._clean_markdown_links(text, references, external_links)
        text = self._clean_whitespace(text)
        return text.strip(), Counter(references), external_links

    def _classify(self, target, unknown_means=None):
        """What does this target point at: a note, an attachment, an
        external url, or something else?

        When the extension decides nothing, unknown_means breaks the
        tie: wikilinks lean note, because vault wikilinks rarely
        point at files, while markdown links lean other, because file
        paths are common in that dialect. A trailing slash is a folder,
        never a note.
        """
        if target.startswith(("http://", "https://")):
            return self.EXTERNAL

        without_anchor = target.split("#")[0].strip()
        if without_anchor.endswith("/"):
            return self.OTHER

        extension = Path(without_anchor).suffix.lower()
        if extension in self.ATTACHMENT_EXTENSIONS:
            return self.ATTACHMENT
        if extension in ("", ".md"):
            return self.NOTE
        return unknown_means or self.OTHER

    def _note_name(self, target):
        """Reduce a note target to the bare note name, the canonical
        form of a graph reference.

        Url escapes are decoded (Three%20laws -> Three laws), anchors
        are cut ([[note#section]] refers to note), folders are dropped,
        and only a literal .md suffix is removed. Any other dot stays,
        so a name like Restart Dataset - 1.6.0 survives intact.
        """
        target = unquote(target).split("#")[0].strip()
        if target.endswith(".md"):
            target = target[: -len(".md")]
        return target.split("/")[-1].strip()

    def _clean_embeds(self, text, references):
        """Wikilink embeds: ![[target]] with an optional |size.

        An embedded attachment is pure display, it vanishes without a
        trace. An embedded note is a transclusion, the strongest kind of
        reference: its name stays in the text and joins the graph.

            ![[Pasted image 2026.png|545]]  ->  (gone)
            ![[Meeting Notes.pdf#page=3]]   ->  (gone)
            ![[important-note]]             ->  important-note  (+ edge)
        """
        def replace_embed(match):
            target = match.group(1)
            if self._classify(target, unknown_means=self.NOTE) != self.NOTE:
                return ""
            name = self._note_name(target)
            if name:
                references.append(name)
            return name

        return self.WIKILINK_EMBED.sub(replace_embed, text)

    def _clean_images(self, text):
        """Markdown images: ![alt](file).

        The alt text is a description the author wrote, so it stays.
        Unless it is just a size (250, 100x145), which is display data,
        or empty: then the whole image vanishes.

            ![diagram of the pipeline](x.png)  ->  diagram of the pipeline
            ![](decoration.png)                ->  (gone)
            ![250](banner.jpg)                 ->  (gone)
        """
        def replace_image(match):
            alt_text = match.group(1).strip()
            if not alt_text or self.IMAGE_SIZE.match(alt_text):
                return ""
            return alt_text

        return self.MARKDOWN_IMAGE.sub(replace_image, text)

    def _clean_wikilinks(self, text, references):
        """Wikilinks: [[target]] or [[target|alias]].

        A note target keeps its alias (or its name) as the visible text
        and becomes a graph edge. Attachments and anything else keep
        their name as plain text, with nothing tracked. The edge always
        points at the canonical target, even when an alias is shown.

            [[14-agentic-loop]]            ->  14-agentic-loop  (+ edge)
            [[05-search|the search note]]  ->  the search note  (+ edge to 05-search)
            [[05-search#Basics]]           ->  05-search        (+ edge)
            [[Figure 1.png]]               ->  Figure 1.png     (no edge)
        """
        def replace_wikilink(match):
            target, alias = match.group(1), match.group(2)
            if self._classify(target, unknown_means=self.NOTE) == self.NOTE:
                name = self._note_name(target)
                if name:
                    references.append(name)
                    return alias or name
            return alias or target

        return self.WIKILINK.sub(replace_wikilink, text)

    def _clean_markdown_links(self, text, references, external_links):
        """Markdown links: [label](target).

        The label always stays as the readable text. A note target also
        becomes a graph edge, an external url is stored aside so answers
        can still cite it, and everything else (repo files, dead
        folders) leaves only its label behind.

            [Data Ingestion](09-data-ingestion.md)   ->  Data Ingestion     (+ edge)
            [Watch this lesson](https://youtu.be/x)  ->  Watch this lesson  (+ url stored)
            [rag_helper.py](../code/rag_helper.py)   ->  rag_helper.py      (text only)
        """
        def replace_link(match):
            label, target = match.group(1), match.group(2)
            kind = self._classify(target)
            if kind == self.NOTE:
                name = self._note_name(target)
                if name:
                    references.append(name)
            elif kind == self.EXTERNAL:
                external_links.append(target.strip())
            return label

        return self.MARKDOWN_LINK.sub(replace_link, text)

    def _clean_whitespace(self, text):
        """Trailing spaces go, then three or more line breaks collapse
        into two. Space-padded blank lines count as blank, which plain
        newline matching would miss.

            "line   \\n\\n\\n\\nnext"  ->  "line\\n\\nnext"
        """
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text)