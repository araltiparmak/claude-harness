---
name: visual-check
description: Screenshots web pages at phone and desktop width in light and dark mode with the local Chrome, and lists content wider than the screen and console errors, so a UI change is looked at before it is called done. Use after changing a page's layout, styles, theme or components, before a deploy of a site, or when the user asks to check, screenshot or review how a page looks.
---

# Visual check

A passing build says nothing about how a page looks. After a UI change, look at it:

1. Serve the page. For a dev server, start it in the background and wait until it answers; a static file can be passed as a path.
2. Run `node scripts/shot.mjs <url or file> [more pages] --out <dir>` (this skill's folder). Pass every page the change reaches: a changed component is checked on each page type that uses it. Use the scratchpad as `<dir>`, or `.visual/` in the project when the user wants to keep the images.
3. Each page gives four PNGs: `<page>-390-light`, `-390-dark`, `-1440-light`, `-1440-dark`. Read all four for the pages you changed, and the phone pair for the rest. Look for clipped or overlapping text, low contrast, dark-mode colours that were never set, and spacing that breaks at phone width.
4. Fix every `PROBLEM` line and everything you saw, then run it again. Done means: no `PROBLEM` lines (exit code 0), and the screenshots show what the user asked for.
5. Report the pages checked and what you fixed. Show a screenshot when the change is about how something looks.

A `PROBLEM` line names a page wider than the screen, an element whose box or text runs past the screen edge (a long command in a `<pre>`, a wide table outside a scroll container), a console error or an uncaught exception. Content inside a scrolling or clipping container is not a problem. Pages taller than 6000px are cut; the output says so.

Set `CHROME=/path/to/browser` when Chrome or Edge is not in the usual place.
