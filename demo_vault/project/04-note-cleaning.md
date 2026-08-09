---
tags: [project, ingestion]
---

# Note cleaning

Obsidian markdown is full of syntax that would pollute search and
prompts: wikilinks, embeds, images with size annotations, markdown
links, url-encoded paths, anchors. The cleaner's job is to leave
exactly what a human reader would see in the rendered note, while
extracting the structure (who cites whom, which urls exist) into
metadata fields instead of losing it.

## Every target decides its fate

The cleaner recognizes four syntaxes, processed from most specific to
most generic so the specific rule never gets swallowed by the generic
one: Obsidian embeds `![[target]]`, markdown images `![alt](file)`,
wikilinks `[[target|alias]]` and markdown links `[label](target)`.
Classification looks only at url scheme and file extension, never at
content, so the rules work on any vault:

- An embedded attachment (image, pdf, audio) is pure display: it
  vanishes without a trace.
- An embedded note is a transclusion, the strongest kind of reference:
  its name stays in the text and joins the graph.
- A wikilinked note keeps its alias (or its name) as the visible text
  and becomes a graph edge pointing at the canonical target, even when
  an alias is shown.
- A markdown link always keeps its label as readable text; a note
  target also becomes an edge, an external url is stored aside in
  `external_links` so answers can still cite it, and anything else (a
  repo file, a dead folder) leaves only its label behind.
- Image alt texts survive when the author wrote a real description,
  and vanish when they are just a size (250, 100x145).

Names survive the hard cases: url escapes are decoded (`Three%20laws`
becomes `Three laws`), anchors are cut (`[[note#section]]` refers to
`note`), folders are dropped, and only a literal `.md` suffix is
removed, so a versioned name like `Restart Dataset - 1.6.0` keeps its
dots.

## The weighted note graph

The most valuable extraction is the graph. Every reference to another
note becomes an edge, and repeated citations are counted: `clean()`
returns the references as a Counter, so citing a note four times is a
four times stronger connection than citing it once. The weights
survive flattening into the index as repeated entries in a keyword
field, and consumers rebuild the counts on the way out.

This graph is the foundation of a later phase: following the links of
retrieved notes to expand context, using the relevance signal the
vault's author drew by hand. Retrieval today ignores it; the data is
already in place.

## The torture test

The cleaner was developed against a stress note committed at
`data/cleaner_stress_test.md`: every syntax variation placed inside
every formatting trap, bold, lists, tables, quotes and code fences,
plus things that must NOT match (plain brackets, unclosed wikilinks,
array indexing). One run of the cleaner over it shows every rule
working in a single output, and it doubles as a regression test: any
change to the cleaner reruns it.

That fixture also exposed the one documented limitation: the cleaner
does not parse markdown structure, so link syntax inside code regions
is cleaned like everything else, and fake names from code examples
leak into the reference list. The design answer is a division of
labor: the cleaner reports optimistically, and ghost names get
filtered when the graph is actually built, because only names matching
real notes become nodes.

You are looking at a live demonstration: the syntax examples written
in this very note leak into its own extracted references as the ghost
names `target` and `note`. Ingest this vault and check the metadata of
this file, the limitation documents itself.

Next: [[05-search-and-index]], where the cleaned chunks become
searchable.
