
---

tags: [testing, cleaner]

created: 2026-07-18

author: marcos

---

  

# Cleaner torture test

  

This note exists to break the NoteCleaner. Every link and embed variation

lives here, mixed into realistic prose, lists, quotes, tables and code.

  

## Plain references

  

The basics: see [[14-agent-evaluation]] for evaluation and

[[13-function-calling|the tools note]] when you need function calling.

A link with extension [[05-search.md]] should behave like one without.

Path qualified: [[llm-zoomcamp-2026/01-agentic-rag/03-rag]] points across folders.

Versioned names are cruel: [[Restart Dataset - 1.6.0]] has dots that are not extensions.

Names with spaces exist too: [[My Daily Notes Setup]].

  

## Anchors and blocks

  

Heading anchor: [[05-search#Basics]] and nested [[05-search#Basics#Scoring]].

Block reference: [[2026-01-01#^37066d]] and a readable one [[quotes#^best-quote]].

Same note heading: [[#Plain references]] and same note block: [[#^localblock]].

  

## Attachments referenced as links

  

The figure [[Figure 1.png]] and the sheet [[budget.pdf]] are wikilinked, not embedded.

  

## Embeds

  

Pasted screenshot: ![[Pasted image 20260717130203.png|545]]

Sized both ways: ![[Engelbart.jpg|100x145]] and ![[diagram.svg|300]]

Full note transclusion: ![[important-note]]

Section transclusion: ![[14-agent-evaluation#Setup]]

Documents: ![[Doc.pdf]] and ![[Doc.pdf#page=3]] and ![[Doc.pdf#height=400]]

Media: ![[Excerpt from the demo (1968).ogg]] and ![[recording.mp4]]

Canvas: ![[My canvas.canvas]]

  

## Markdown dialect

  

Simple: [Data Ingestion →](09-data-ingestion.md) continues the flow.

With path: [the rag lesson](llm-zoomcamp-2026/01-agentic-rag/03-rag.md)

Url encoded: [three laws](Three%20laws%20of%20motion.md)

With anchor: [search basics](05-search.md#Basics)

Repo file: [rag_helper.py](../code/rag_helper.py) and dead folder [code/](../code/)

External: [Watch this lesson](https://www.youtube.com/watch?v=KHePGkeFn54&list=PL3MmuxUbc_hL)

Tricky url with parens: [wiki](https://en.wikipedia.org/wiki/Test_(unit))

  

Images: ![diagram of the whole pipeline](assets/pipeline.png) has meaning,

![](no-alt.png) has none, ![250](https://img.site/banner.jpg) is a size in disguise,

and ![100x145](thumb.png) too.

  

## Formatting traps

  

Two on one line: [[note-a]] and [[note-b]] should both survive.

Inside bold: **[[bold-note]]** and inside a list:

  

- first item links [[list-note-1]]

- second item embeds ![[list-image.png|200]]

- third has [external](https://site.com/page?a=1&b=2)

  

> A quote citing [[quoted-note]] and [a doc](quoted-doc.md).

  

| col a | col b |

| ----- | ----- |

| [[table-note]] | [cell link](cell-note.md) |

  

## Things that are NOT links

  

Plain brackets [like this] are prose. Empty [] too.

An unclosed [[broken wikilink stays as is.

An orphan closer ](orphan.md) has no opening.

Array indexing a[0] and dict access d["key"] are code, not links.

  

## Code regions, the known limitation

  

Inline code mentions `[[fake-link]]` and code fences contain syntax:

  

```python

# this looks like links but is code:

x = data[[1, 2]]

url = "[label](https://example.com)"

note = "[[not-a-real-reference]]"

```

  

The cleaner does not parse markdown structure, so syntax inside code

regions gets cleaned like everything else. Documented as a limitation.

  

## Whitespace stress

  
  
  
  

Three blank lines above, trailing spaces here.  

And the end comes after one more gap.

  
  
  

Done.