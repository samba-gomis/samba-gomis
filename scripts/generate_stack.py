#!/usr/bin/env python3
"""
Scans every public, non-fork repo of USERNAME and rewrites the stack badges
block in README.md (between START_MARKER and END_MARKER) from what it finds:
- languages actually used (GitHub languages API)
- frameworks/libs declared in package.json, requirements.txt, pom.xml
- deployment/tooling config files (render.yaml, netlify.toml, Dockerfile, pom.xml)

Run manually with `python scripts/generate_stack.py`, or via the
.github/workflows/update-stack.yml Action (daily + on demand).
No new project needs any manual edit here: add a repo with a recognized
manifest/language and it shows up on the next run.
"""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

USERNAME = "samba-gomis"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

START_MARKER = "<!-- STACK:AUTO:START -->"
END_MARKER = "<!-- STACK:AUTO:END -->"

# label -> (shields logo slug or None, logoColor or None, category)
CATALOG = {
    # languages
    "Python":       ("python", "3776AB", "lang"),
    "Java":         ("openjdk", "ED8B00", "lang"),
    "TypeScript":   ("typescript", "3178C6", "lang"),
    "JavaScript":   ("javascript", "F7DF1E", "lang"),
    "C":            ("c", "A8B9CC", "lang"),
    "C++":          ("cplusplus", "00599C", "lang"),
    "HTML5":        ("html5", "E34F26", "lang"),
    "CSS3":         ("css3", "1572B6", "lang"),
    # frontend
    "React":        ("react", "61DAFB", "frontend"),
    "Next.js":      ("nextdotjs", "ffffff", "frontend"),
    "Tailwind CSS": ("tailwindcss", "38B2AC", "frontend"),
    "Sass":         ("sass", "CC6699", "frontend"),
    # backend / desktop
    "Express":      ("express", "ffffff", "backend"),
    "JavaFX":       (None, None, "backend"),
    "Flask":        ("flask", "ffffff", "backend"),
    "Django":       ("django", "092E20", "backend"),
    "PyGame":       ("python", "a78bfa", "backend"),
    "Tkinter":      ("python", "60a5fa", "backend"),
    # data
    "PostgreSQL":   ("postgresql", "336791", "data"),
    "MySQL":        ("mysql", "4479A1", "data"),
    # tools
    "Git":          ("git", "F05033", "tools"),
    "Maven":        ("apachemaven", "C71A36", "tools"),
    "Render":       (None, None, "tools"),
    "Netlify":      ("netlify", "00C7B7", "tools"),
    "Docker":       ("docker", "2496ED", "tools"),
}

CATEGORY_TITLES = {
    "lang": "Langages",
    "frontend": "Frontend & Frameworks",
    "backend": "Backend & Desktop",
    "data": "Bases de données",
    "tools": "Outils & Déploiement",
}
CATEGORY_ORDER = ["lang", "frontend", "backend", "data", "tools"]

LANG_API_MAP = {
    "Python": "Python", "Java": "Java", "TypeScript": "TypeScript",
    "JavaScript": "JavaScript", "C": "C", "C++": "C++",
    "HTML": "HTML5", "CSS": "CSS3", "SCSS": "Sass",
}

NPM_DEP_MAP = {
    "react": "React", "react-dom": "React", "next": "Next.js",
    "tailwindcss": "Tailwind CSS", "@tailwindcss/postcss": "Tailwind CSS",
    "express": "Express", "mysql2": "MySQL", "mysql": "MySQL",
    "pg": "PostgreSQL", "sass": "Sass",
}

PY_REQ_MAP = {
    "pygame": "PyGame", "customtkinter": "Tkinter", "tkinter": "Tkinter",
    "flask": "Flask", "django": "Django",
}

POM_ARTIFACT_MAP = {
    "postgresql": "PostgreSQL", "javafx-controls": "JavaFX",
    "javafx-fxml": "JavaFX", "javafx-swing": "JavaFX",
}

CONFIG_FILE_MAP = {
    "render.yaml": "Render", "netlify.toml": "Netlify", "Dockerfile": "Docker",
}


def api_get(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "stack-bot"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def raw_get(owner, repo, branch, path):
    url = f"{RAW}/{owner}/{repo}/{branch}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "stack-bot"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None


def list_repos():
    repos, page = [], 1
    while True:
        batch = api_get(f"/users/{USERNAME}/repos?per_page=100&page={page}&type=owner")
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r["fork"]]


def find_pom(owner, repo, branch):
    for path in ("pom.xml", "demo/pom.xml"):
        content = raw_get(owner, repo, branch, path)
        if content:
            return content
    return None


def detect_all():
    found = set()
    found.add("Git")

    for repo in list_repos():
        name = repo["name"]
        branch = repo.get("default_branch") or "main"

        try:
            langs = api_get(f"/repos/{USERNAME}/{name}/languages")
        except Exception:
            langs = {}
        for lang in langs:
            if lang in LANG_API_MAP:
                found.add(LANG_API_MAP[lang])

        pkg = raw_get(USERNAME, name, branch, "package.json")
        if pkg:
            try:
                deps = {**json.loads(pkg).get("dependencies", {}),
                        **json.loads(pkg).get("devDependencies", {})}
                for dep in deps:
                    if dep in NPM_DEP_MAP:
                        found.add(NPM_DEP_MAP[dep])
            except json.JSONDecodeError:
                pass

        for reqname in ("requirements.txt", "Requirements.txt"):
            req_txt = raw_get(USERNAME, name, branch, reqname)
            if req_txt:
                for line in req_txt.splitlines():
                    pkgname = re.split(r"[=<>~\[;\s]", line.strip().lower())[0]
                    if pkgname in PY_REQ_MAP:
                        found.add(PY_REQ_MAP[pkgname])
                break

        pom = find_pom(USERNAME, name, branch)
        if pom:
            found.add("Maven")
            found.add("Java")  # a pom.xml always implies a Java project
            for artifact, label in POM_ARTIFACT_MAP.items():
                if artifact in pom:
                    found.add(label)

        for fname, label in CONFIG_FILE_MAP.items():
            if raw_get(USERNAME, name, branch, fname) is not None:
                found.add(label)

    return found


def badge_url(label, logo, color):
    text = label.replace(" ", "%20").replace("+", "%2B").replace("#", "%23")
    url = f"https://img.shields.io/badge/{text}-0d1117?style=for-the-badge"
    if logo:
        url += f"&logo={logo}"
    if color:
        url += f"&logoColor={color}"
    return url


def render_markdown(found_labels):
    by_category = {cat: [] for cat in CATEGORY_ORDER}
    for label in found_labels:
        logo, color, category = CATALOG[label]
        by_category[category].append((label, logo, color))

    lines = []
    for cat in CATEGORY_ORDER:
        items = sorted(by_category[cat])
        if not items:
            continue
        lines.append(f"### {CATEGORY_TITLES[cat]}")
        badges = " ".join(
            f"![{label}]({badge_url(label, logo, color)})" for label, logo, color in items
        )
        lines.append(badges)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    found = detect_all() & set(CATALOG)
    new_block = render_markdown(found)

    readme = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    replacement = f"{START_MARKER}\n{new_block}{END_MARKER}"
    if not pattern.search(readme):
        raise SystemExit("Markers not found in README.md")
    updated = pattern.sub(replacement, readme)

    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")
        print("README.md stack section updated.")
    else:
        print("No change.")


if __name__ == "__main__":
    main()
