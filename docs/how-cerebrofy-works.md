# How Cerebrofy Works
### A plain-language guide for everyone on the team

---

## The problem it solves

When an AI assistant (like Claude, Copilot, or Cursor) helps you with code, it needs to read the code first. For a small project that's fine. But as projects grow — hundreds of files, thousands of functions — the AI has to read enormous amounts of code just to answer a simple question. This is slow, expensive, and the AI often gets confused because it has too much to hold in memory at once.

**Cerebrofy solves this by building a map of your codebase** — like an index at the back of a book. Instead of reading every page, the AI looks up exactly what it needs, goes straight to it, and reads only that.

---

## What it actually builds

When you run Cerebrofy, it reads every source file in your project and builds three things:

**1. A knowledge graph**
Every function, class, and module in your codebase becomes a *neuron* (a node in the graph). Every time one function calls another, or one file imports another, that becomes an *edge* (a connection between nodes). The result is a complete map of how everything in your code relates to everything else.

**2. A meaning index**
Each neuron is also converted into a mathematical fingerprint — a list of 384 numbers that captures what that piece of code *means* (not just its name). This lets the AI find code by meaning, not just by exact name. Ask "find me the login flow" and it finds the relevant functions even if none of them are literally called `login`.

**3. Lobe summaries**
Your project is divided into *lobes* — named sections (e.g. `api`, `auth`, `database`, `ui`). Cerebrofy writes a plain-language summary file for each lobe that the AI can read first to orient itself before diving into specifics.

Everything is stored in a single file: `.cerebrofy/db/cerebrofy.db` inside your project. Nothing ever leaves your machine.

---

## How you set it up (once per project)

```
cerebrofy init
```

That's it. This one command does three things automatically:

- Creates the `.cerebrofy/` folder inside your project
- Installs a git hook (explained below)
- Registers Cerebrofy with your AI assistant so it can use the map

Then run the first build:

```
cerebrofy build
```

This scans your entire codebase and builds the map for the first time. On a medium-sized project (a few thousand files) it takes under a minute. On very large projects, a few minutes. You only run this once — or after a Cerebrofy upgrade.

---

## Day-to-day: you don't do anything

After the first setup, Cerebrofy works silently in the background.

**When you edit code and push it:**
A git hook runs automatically before your push goes through. It checks whether your changes have made the map stale (this check takes under a second). If everything is still in sync, your push goes through normally. If your changes affected the structure of the code, you'll see:

```
Cerebrofy: Structural drift detected. Run cerebrofy update to sync.
```

You run:

```
cerebrofy update
```

This re-indexes only the files you changed — not the whole project. It typically finishes in under 2 seconds. Then your push goes through.

**That's the entire daily workflow.** Edit → commit → push → if prompted, run `cerebrofy update` → done.

---

## What your AI assistant gets

Once Cerebrofy is set up, your AI assistant (Claude Code, Copilot, Cursor, etc.) automatically has access to six tools through what's called an MCP server — a background service that Cerebrofy runs:

---

### Tool 1: `search_code`
**What it does:** The AI asks a question in plain language — "find me the part that handles password validation" — and gets back a ranked list of the exact functions and classes in your codebase that are relevant, with the file name and line number for each.

**Why it matters:** Without this, the AI would have to read dozens of files hoping to stumble across the right code. With this, it jumps straight to the relevant 3–5 locations.

*This tool uses the meaning index (vector search) to find semantically related code, then follows the connection graph outward (BFS traversal) to also return everything that is directly connected to what it found. You get not just the match, but the full local neighbourhood of related code.*

---

### Tool 2: `get_neuron`
**What it does:** The AI looks up a specific function or class by name (or by file and line number) and gets back its full signature, docstring, and location.

**Why it matters:** After finding something via `search_code`, the AI can pull up the exact details of any specific item without reading the entire file it lives in.

---

### Tool 3: `list_lobes`
**What it does:** Returns a list of all the named sections (lobes) of your codebase, with a path to the summary file for each.

**Why it matters:** When the AI needs to orient itself in an unfamiliar project, it reads the lobe list first to understand the lay of the land before asking more specific questions. It's the table of contents.

---

### Tool 4: `cerebrofy_build`
**What it does:** Triggers a full rebuild of the entire index.

**Why it matters:** The AI can rebuild the map itself if it detects the index is missing or heavily out of date — without you having to open a terminal.

---

### Tool 5: `cerebrofy_update`
**What it does:** Triggers an incremental re-index of changed files only.

**Why it matters:** Same as above — the AI can keep the index fresh mid-session if needed.

---

### Tool 6: `cerebrofy_validate`
**What it does:** Checks whether the current index matches the current state of the code. Returns one of three states: *clean* (perfectly in sync), *minor drift* (small cosmetic changes, index is still usable), or *structural drift* (functions were added, removed, or renamed — index needs updating).

**Why it matters:** Before the AI answers a deep structural question about your code, it can first verify the map is up to date. Asking for directions with a stale map is worse than no map at all.

---

## The full picture: what happens when you ask the AI a question

Here is the complete flow from your question to the AI's answer, once Cerebrofy is running:

```
You:  "How does the payment retry logic work?"

AI:   1. Calls list_lobes        → finds the 'billing' lobe and reads its summary
      2. Calls search_code       → asks "payment retry logic"
                                 → Cerebrofy embeds the question,
                                    finds the 3 most semantically similar functions,
                                    follows their connections outward,
                                    returns 8 precise locations (file:line)
      3. Calls get_neuron        → pulls the signature + docstring for the top 2 hits
      4. Reads only those files  → reads ~40 lines total instead of 3,000

You:  Get a precise, accurate answer in seconds
      instead of a slow, hallucination-prone sweep of the whole repo
```

Without Cerebrofy, step 2–4 would be replaced by the AI reading entire files, often 5–15 of them, hoping to find the relevant code. With Cerebrofy, it goes straight to the source.

---

## What Cerebrofy does NOT do

Being clear about boundaries is important:

- **It does not write code.** It only helps the AI find code faster.
- **It does not send your code anywhere.** Everything — the graph, the embeddings, the index — lives in `.cerebrofy/db/` inside your project. No cloud, no API calls, no internet connection needed after installation.
- **It does not replace your AI assistant.** It makes your existing AI assistant faster and more accurate.
- **It does not change how you work.** You write code exactly as you always have. The only new habit is running `cerebrofy update` when prompted after a push.
- **It does not read configuration files, markdown, or non-code files.** It indexes source code (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, and others as configured). Docs and configs are not indexed.

---

## The complete command reference

| Command | When to run it | How long it takes |
|---|---|---|
| `cerebrofy init` | Once, when setting up a project | A few seconds |
| `cerebrofy build` | Once after init; again after a Cerebrofy upgrade | 30s – 3 min depending on project size |
| `cerebrofy update` | When the git hook asks you to (after pushing) | Under 2 seconds |
| `cerebrofy validate` | If you're unsure whether the index is current | Under 1 second |
| `cerebrofy migrate` | After a Cerebrofy version upgrade changes the index format | A few seconds |

You will almost never need to run anything except `cerebrofy update`, and only when the git hook tells you to.

---

## Why the index lives inside your repo

`.cerebrofy/db/` is listed in `.gitignore` — the database is not committed to version control. Each developer builds their own local index from the source code. This means:

- No large binary files in your git history
- Each developer's index is always built from the exact version of the code they have checked out
- There is no shared state to go out of sync between team members

When a new developer joins, they run `cerebrofy init` and `cerebrofy build` once. From that point on, `cerebrofy update` keeps their index current automatically.

---

*Cerebrofy is a local-first, offline-capable codebase intelligence tool. No data leaves your machine.*
