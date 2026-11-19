# PDF and Markdown readers: interface map

Acrobat Reader, Edge's viewer, macOS Preview, PDF.js (Firefox), Obsidian, Typora, VS Code's preview and GitHub's rendered view, researched on 2026-11-11 for the Mitra interface review.

**How to read this.** Claims come from official documentation unless marked. "Not verified" means no source was found and nothing was guessed. Adobe documents Acrobat and Reader together and restructured its help site, so some old pages redirect. Nobody opened the products to check the screens.

## What a good reader has

Ordered by how many of the products have it.

**PDF reader**

1. Find in document, with next and previous and all matches highlighted (all four).
2. Zoom in and out, fit width, fit page; a page-number box with go-to-page (all four).
3. An outline pane built from the PDF's bookmarks (all four).
4. Select and copy text (all four).
5. Rotate; single, continuous and two-page layouts (all four, in varying depth).
6. Highlight and notes on selected text, saved with the file (all four in some form).
7. Page thumbnails (Acrobat, Preview, PDF.js; Edge not verified).
8. Form filling (Acrobat, Edge, Preview).
9. Full screen or presentation mode (Acrobat, Preview, PDF.js).
10. One list of all highlights and comments (Acrobat, Preview).
11. Read aloud (Acrobat, Edge).
12. Search options: whole word, case, a results list with context (Acrobat; partly Preview).
13. View history, search across many files, document properties, replaced page colours, reflow, tabs with recent and starred files (Acrobat only).
14. Cited AI answers that jump to the source passage (Acrobat, paid).

**Markdown reader**

1. A rendered view with a source toggle (all four).
2. A heading outline that jumps on click (all four).
3. Highlighted code blocks, tables, task lists, images (all four).
4. Heading anchors and relative or internal links (all four).
5. Mermaid diagrams (all four).
6. Math (Obsidian, Typora, VS Code).
7. Find in document, plus search across files (Obsidian, Typora, VS Code).
8. A file tree and quick open (Obsidian, Typora, VS Code).
9. Front matter handled on purpose: shown, hidden or raw (Obsidian, Typora).
10. Themes or custom CSS; a readable line width (Obsidian, Typora, VS Code).
11. Export to PDF or HTML (Typora).
12. Source and preview side by side with synced scrolling (VS Code, Obsidian).
13. Backlinks and tabs (Obsidian); focus and typewriter modes (Typora).

## Acrobat Reader

Menu paths are for Windows.

1. **Layout.** Three views: Home, All tools, Document. A global bar with All tools, Edit, Convert, E-sign, plus Search, Save, Print, Share. Each PDF opens as a tab. All tools opens as the left panel. A floating, customisable quick-action toolbar offers select, comment, highlight, draw, fill and sign. The right panel has Comments, Bookmarks, Page thumbnails and Articles at the top, and the page-number box, arrows, rotate, page display and zoom at the bottom. In the classic interface the navigation panels were on the left and tools on the right; you can switch back from the menu. ([workspace](https://helpx.adobe.com/acrobat/desktop/get-started/learn-the-basics/workspace.html))
2. **Navigation.** Next, Previous, First, Last, Go to page (Ctrl+Shift+N); Previous view and Next view retrace your path; a bookmarks panel; thumbnails with a draggable box that pans and zooms the page; article threads; automatic scrolling. ([navigation](https://helpx.adobe.com/acrobat/desktop/get-started/learn-the-basics/navigation.html))
3. **View modes.** Single page, scrolling, two-page, two-page scrolling. Zoom: actual size, fit page, fit width, fit height, fit visible, marquee, dynamic, pan-and-zoom window, loupe. Rotate in 90° steps (not saved). Read Mode hides the bars and shows a floating toolbar. Full screen with Ctrl+L. Split window and a four-pane spreadsheet split. The display theme changes the application chrome only; page colours change only through the accessibility setting "Replace Document Colors", so there is no dedicated night mode. Reflow (Ctrl+4) for tagged PDFs. Liquid Mode is mobile only. ([views](https://helpx.adobe.com/acrobat/using/adjusting-pdf-views.html))
4. **Search.** Find (Ctrl+F) offers whole words, case sensitive, include bookmarks, include comments; it suggests matching words with counts as you type and highlights all matches. Advanced Search opens in its own window: scope is the current PDF, all PDFs in a folder, or an index; matching by exact phrase, any words, all words or Boolean, with proximity and stemming; results are nested per document in page order with a few words of context, sortable, and can be saved as PDF or CSV. ([searching](https://helpx.adobe.com/acrobat/using/searching-pdfs.html))
5. **Annotation in the free Reader.** Sticky notes, typed text, highlight, underline, strikethrough, freehand drawing ([Reader FAQ](https://helpx.adobe.com/reader/desktop/faq.html)). Comments are added from the quick-action toolbar or the toolbar that appears on a text selection. The comments pane sorts and filters by page, author, date, type and colour, and has its own search (from an older page; not re-verified).
6. **Text operations.** Select text or an image and copy; Take a Snapshot copies an area as an image; copying is blocked if the document's security disallows it. Converting to Word or Excel is paid. ([copy content](https://helpx.adobe.com/reader/desktop/copy-content-pdfs.html))
7. **Forms and signing.** Fill & Sign fills interactive fields or lets you type on a flat form; signatures can be typed, drawn or an image.
8. **Reading aids.** Read Out Loud using system voices; an accessibility setup assistant; replaced document colours for high contrast; full keyboard coverage, with F6 moving between the document and panels. ([accessibility](https://helpx.adobe.com/reader/desktop/accessibility-features.html))
9. **Document information.** Properties tabs: Description (title, author, subject, keywords, dates), Security, Fonts, Initial View, Custom. ([properties](https://helpx.adobe.com/acrobat/desktop/edit-documents/edit-pdf-properties/pdf-properties.html))
10. **AI Assistant (paid add-on).** Ask a question about the PDF; answers carry numbered citations, and selecting a number jumps to the passage and highlights it. A generative-summary button sits in the right panel. ([AI answers](https://helpx.adobe.com/acrobat/desktop/use-acrobat-ai/generative-ai-features/ai-get-answers.html))
11. **Recent files.** Home has Recent (list or thumbnails), Starred, cloud files and other storage, with a file search box. A preference restores the last-viewed page when a document is reopened.
12. **Complaints.** The new interface hides or moves tools and adds clicks; many users revert to classic ([forum](https://community.adobe.com/questions-9/why-change-everything-1283123)). Paid and AI prompts are prominent in the reading interface (inferred from the help pages). No citable praise was found; its depth of search and view options is the evident strength.

## Other PDF viewers

**Microsoft Edge** ([docs](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-pdf))
- Toolbar: zoom, rotate, fit to page or width, jump to page, search, print.
- A table-of-contents pane for PDFs that have an outline; single or two-page view.
- Highlight in several colours from the right-click menu; text notes on a selection; inking.
- Read aloud that highlights the text being read; caret browsing with F7.
- Basic form filling; follows the system's high-contrast setting.

**macOS Preview** ([docs](https://support.apple.com/guide/preview/view-pdfs-and-images-prvw11470/mac))
- Sidebar: Thumbnails, Table of Contents, Highlights and Notes, Bookmarks, Contact Sheet.
- Continuous scroll, single page, two pages; zoom to selection; a magnifier; Go to Page.
- Search with exact phrase or any match; results ordered by rank or by page.
- Highlight, underline, strikethrough, with a sticky mode that applies the style to each later selection; notes, shapes, signatures, form filling.

**PDF.js (Firefox)** ([FAQ](https://github.com/mozilla/pdf.js/wiki/Frequently-Asked-Questions))
- Page navigation, zoom, rotate, presentation mode, hand tool, text selection, find, download, print.
- A sidebar with thumbnails and the document outline.
- Highlight with colours, add text, draw, add images.

## Markdown tools

**Obsidian.** Reading view and an editing view with Live Preview and Source mode; Ctrl+E switches; both can sit side by side ([views](https://obsidian.md/help/edit-and-read)). An outline of headings that jumps on click ([outline](https://obsidian.md/help/plugins/outline)). Internal links, embeds and backlinks with context ([backlinks](https://obsidian.md/help/plugins/backlinks)). Tabs, splits and pinning. Highlighted code, tables, clickable task boxes, callouts, footnotes, math, Mermaid. Front matter ("properties") can be visible, hidden or shown as source. Search across the vault with operators such as `file:`, `tag:` and `line:`, with regex and "show more context" ([search](https://obsidian.md/help/plugins/search)). A "readable line length" setting.

**Typora.** One pane that renders as you type and hides the markers; a source mode ([quick start](https://support.typora.io/Quick-Start/)). A sidebar with Outline, File Tree or File List. Quick open, find, and search across files. Focus Mode dims everything but the current block; Typewriter Mode keeps the cursor centred ([modes](https://support.typora.io/Focus-and-Typewriter-Mode/)). Tables with a graphical editor, task lists, highlighted code, math, an auto-updating table of contents, footnotes, Mermaid. Word count; themes as CSS files. Export to PDF, HTML and image.

**VS Code preview.** A preview that updates live and scrolls in step with the source; double-click jumps to the source line ([docs](https://code.visualstudio.com/docs/languages/markdown)). The Outline view shows the heading tree; go-to-symbol works within the file and across the workspace. Link validation and find-all-references on headings. Math and Mermaid render. Custom CSS.

**GitHub rendered view.** An outline button when a file has two or more headings; hover a heading for its link; relative links between files; a button to switch to source with line links ([docs](https://docs.github.com/en/repositories/working-with-files/using-files/working-with-non-code-files)). Task lists, footnotes, alerts, highlighted code, Mermaid.
