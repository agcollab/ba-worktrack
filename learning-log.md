# BA WorkTrack – Learning Log

Rule: before every commit, write three lines explaining what changed and why, in my own words.

---

## Day 1 – 10/08/2026 – Install tools, create repository

- **Installed:** Python 3.12, VS Code (+ Python, Pylance, Ruff, GitLens, SQLite Viewer), Git, GitHub CLI, Bruno, DB Browser for SQLite, Ollama (llama3.1:8b).
- **Why:** Python + VS Code to write/run the app; Git + GitHub to save snapshots and share them; Bruno to test APIs; DB Browser to look inside SQLite; Ollama to run the AI model locally for free.
- **Git in my own words:** <working folder → `git add` (staging) → `git commit` (snapshot) → `git push` (upload to GitHub)>.

Questions / blockers:
-

## Day 3 – 10/08/2026 – JSON round trip and tests

- I gave `t3` a concrete due date so the saved task includes an actual calendar date.
- The JSON round trip turns the date into text and back, so comparing the loaded tasks with the originals checks that nothing was lost.
- I started P14 with a test for that round trip so the serialization behavior can be checked automatically.
