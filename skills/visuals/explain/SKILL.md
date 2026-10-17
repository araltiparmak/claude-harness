---
name: explain
description: Builds a one-page brief that explains a feature or technical topic to developers, testers and a product manager at once: summary and scope, where it lives (D2, whiteboard style), the flow (Mermaid sequence), states, a decision table, rules with concrete examples, and open questions, shareable as one HTML file or an Artifact. Use when the user wants to explain a feature or change across roles, align developers and testers, write a feature brief or explainer page, spell out a business rule that depends on several conditions, or share a technical topic with a PM.
---

# Explain

One page per topic, so developers, testers and a PM look at the same picture. Each section carries a tag naming the reader it serves. Diagrams come from the `diagrams` skill's renderer; its `d2.md` and `mermaid.md` rules apply to the sources here.

## Steps

1. **Pin down the topic**: the behavior in one sentence, what is in and out of scope, the rules. Take them from the user, the code and the conversation. A rule, number or owner you cannot find becomes an open question, not a guess.
2. **Copy `example/`** to `docs/explain/<topic>/` in the project, or to the scratchpad for a throwaway.
3. **Write the sources**, one file per picture, and delete the example ones you do not need:
   - `architecture.d2`: where the change lives. Label what is new.
   - `<flow>.mmd`: a Mermaid `sequenceDiagram` with `autonumber`, the happy path and the failure path (`alt`, `opt`).
   - `<thing>-states.mmd`: a `stateDiagram-v2`, only when the thing has states.
4. **Write `page.html`**: replace every piece of example content, keeping the sections in this order. Drop a section that has nothing to say.

   | Section | Tags | Content |
   |---|---|---|
   | Summary | PM | Why, in plain words, plus in scope and out of scope |
   | Where it lives | PM, Dev, Test | `architecture` diagram |
   | The flow | Dev, Test | sequence diagram; the caption names the step most likely to be missed |
   | States | Test, Dev | state diagram; the caption says every arrow is a test case and any move not drawn must be rejected |
   | Decision table | Test, PM, Dev | for a rule that picks an outcome from several conditions: one column per condition, one outcome column, one row per combination, `(any)` where a condition does not matter. Every combination gets a row; a combination nobody specified gets an open question instead of an outcome |
   | Rules and examples | Test, PM | one card per rule: a testable sentence and Given / When / Then rows with concrete values, IDs `R1.1`, `R1.2` |
   | Open questions | PM | `Q1`, `Q2`, each with the role that answers it |

   Each `<img src="<!--svg:NAME-->">` names a source file without its extension. Set its `width` so diagram text reads near body size; a wide diagram scrolls inside its panel.
5. **Build**: `scripts/build.sh docs/explain/<topic>`. It renders every source into `out/` (D2 in the whiteboard style) and writes `index.html` with the diagrams inlined. Fix every `FAIL` it prints.
6. **Check**: read each PNG in `out/`, then look at `index.html` once. Done means: every component, step and state has the same name in every diagram and in the text, the diagrams agree with each other, the decision table covers every combination, every rule has at least one example, and every unknown is an open question.
7. **Share**: when the Artifact tool is available, publish `index.html`, and tell the user that teammates can open it only after it is shared from the page's Share menu. Otherwise hand over the path. Report the source folder and the page.

## Writing

- The summary is for someone outside the team: the customer or business effect first, no internal names.
- Write the page in the language the user asks for. File names, IDs and code stay English.
- The example is a full page for an order that expires after 30 minutes; its footer says it is sample content. Replace the footer too.
