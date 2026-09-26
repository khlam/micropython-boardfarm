---
name: talking-to-a-user
description: Write every user-facing message and documentation file for a reader whose only context is the previous replies or visible content. Use whenever composing any text the user will read or writing documentation files.
---

# Talking to a user

Assume the reader,

* has **no prior context of the task** beyond what they asked for or what is visible;
* has read **only the assistant text up to and including the previous response**, or knows only stated facts;
* has **not** read the tool calls, commands, diffs, hidden file contents, search results, or reasoning that produced the answer.

When writing,

* **Avoid clichés.** Never use a metaphor, simile, or figure of speech.
* **Keep it short.** Never use a long word where a short one will do.
* **Limit length.** Use at most 1000 words per response or documentation section unless the user asks for more. Mermaid diagrams do not count toward this limit.
* **Cut dead weight.** If it is possible to cut a word out, always cut it out.
* **Prefer active voice.** Never use the passive where you can use the active.
* **Use plain English.** Never use a foreign phrase, scientific word, or jargon word if you can find an everyday equivalent.
* **Use markdown illustrations.** When writing in markdown, use Mermaid diagrams to illustrate multi-step flows and system architecture.