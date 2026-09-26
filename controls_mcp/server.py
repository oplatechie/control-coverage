"""controls-mcp: the only way the Control Coverage agent touches GitHub.

Runs on the harness host (never in the sandbox). The GitHub token is read from .env and is
scoped to one repo (DEMO_REPO). Checks that protect the release are enforced here, in code:

  get_controls         read      bank-wide standards and controls from the source of record (GRC API or file)
  get_release_scope    read      commits, merged PRs, reviews, maker-checker gaps between two refs
  create_issue         write     open an issue (reversible)
  add_controls         write     PR that ADDS new files under controls/ only (rejects existing paths)
  propose_fix          write     PR with a proven fix patch to APP code only (rejects controls/, tests/, CI)
  change_controls      DESTRUCTIVE  PR that modifies/deletes files under controls/  -> approval required
  create_release       DESTRUCTIVE  tag + GitHub release, only for a cleared verdict -> approval required
"""
import base64
import hashlib
import json
import subprocess
import tempfile
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

REPO = os.environ.get("DEMO_REPO", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
PORT = int(os.environ.get("CONTROLS_MCP_PORT", "8801"))
API = "https://api.github.com"
# Source of record for controls: an https URL (e.g. the bank's GRC system export) or a file path.
CONTROLS_SOURCE = os.environ.get("CONTROLS_SOURCE") or str(ROOT / "skills/control-coverage/controls.yaml")

mcp = FastMCP("controls-mcp", host="127.0.0.1", port=PORT)
READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


class GitHubError(Exception):
    pass


def gh(method, path, body=None, ok404=False):
    req = urllib.request.Request(
        f"{API}/repos/{REPO}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "controls-mcp"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if ok404 and e.code == 404:
            return None
        raise GitHubError(f"GitHub {method} {path} -> {e.code}: {e.read().decode()[:300]}") from e


def _path_exists_on_main(path):
    return gh("GET", f"/contents/{path}?ref=main", ok404=True) is not None


def _check_controls_path(path):
    if not path.startswith("controls/") or ".." in path or path.startswith("controls/../"):
        raise GitHubError(f"refused: {path} is outside controls/")


def _open_pr(branch, title, body, files, deletions=()):
    main_sha = gh("GET", "/git/ref/heads/main")["object"]["sha"]
    gh("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": main_sha})
    for path, content in files.items():
        existing = gh("GET", f"/contents/{path}?ref={branch}", ok404=True)
        payload = {"message": f"{title}: {path}", "branch": branch,
                   "content": base64.b64encode(content.encode()).decode()}
        if existing:
            payload["sha"] = existing["sha"]
        gh("PUT", f"/contents/{path}", payload)
    for path in deletions:
        existing = gh("GET", f"/contents/{path}?ref={branch}")
        gh("DELETE", f"/contents/{path}", {"message": f"{title}: delete {path}", "branch": branch,
                                           "sha": existing["sha"]})
    pr = gh("POST", "/pulls", {"title": title, "head": branch, "base": "main", "body": body})
    return {"pr": pr["number"], "url": pr["html_url"], "branch": branch}


def _branch_name(prefix, title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return f"{prefix}/{slug}-{os.urandom(2).hex()}"


@mcp.tool(annotations=READ)
def get_controls(standard_ids: list[str] | None = None) -> dict:
    """Bank-wide standards and their controls, from the source of record (CONTROLS_SOURCE).
    Returns YAML text and a version hash for the evidence. Pass standard_ids to fetch only some
    standards (keeps context small when the catalogue is large)."""
    if CONTROLS_SOURCE.startswith("https://"):
        with urllib.request.urlopen(CONTROLS_SOURCE) as r:
            text = r.read().decode()
    else:
        text = Path(CONTROLS_SOURCE).read_text()
    version = hashlib.sha256(text.encode()).hexdigest()[:12]
    if standard_ids:
        import yaml  # only needed for filtering
        data = yaml.safe_load(text)
        data["standards"] = [s for s in data["standards"] if s["id"] in set(standard_ids)]
        text = yaml.safe_dump(data, sort_keys=False)
    return {"source": CONTROLS_SOURCE if not CONTROLS_SOURCE.startswith("/") else "controls.yaml (bundled)",
            "version": version, "yaml": text}


@mcp.tool(annotations=READ)
def get_release_scope(base: str, head: str) -> dict:
    """Commits and merged PRs between two refs (tags, branches or SHAs) of the target repo, with reviews.
    Also computes maker-checker: every merged PR must have an APPROVED review from someone who is
    neither the PR author nor an author of its commits. Returns `gaps` for PRs that fail this.
    Use base="" for the whole history up to head."""
    head_sha = gh("GET", f"/commits/{head}")["sha"]
    if base:
        cmp = gh("GET", f"/compare/{base}...{head}")
        commits = cmp["commits"]
        files = [f["filename"] for f in cmp.get("files", [])]
    else:
        commits = gh("GET", f"/commits?sha={head}&per_page=100")
        files = []
    prs = {}
    for c in commits:
        for pr in gh("GET", f"/commits/{c['sha']}/pulls"):
            if pr.get("merged_at") and pr["number"] not in prs:
                prs[pr["number"]] = pr
    rows, gaps = [], []
    for number, pr in sorted(prs.items()):
        author = pr["user"]["login"]
        committers = {c["author"]["login"] for c in gh("GET", f"/pulls/{number}/commits") if c.get("author")}
        approvals = sorted({r["user"]["login"] for r in gh("GET", f"/pulls/{number}/reviews")
                            if r["state"] == "APPROVED"})
        independent = [a for a in approvals if a != author and a not in committers]
        full = gh("GET", f"/pulls/{number}")
        row = {"number": number, "title": pr["title"], "author": author, "commit_authors": sorted(committers),
               "approved_by": approvals, "independent_approval": bool(independent),
               "merged_by": (full.get("merged_by") or {}).get("login"), "url": pr["html_url"]}
        rows.append(row)
        if not independent:
            gaps.append(row)
    return {"repo": REPO, "base": base, "head": head, "head_sha": head_sha,
            "commits": [{"sha": c["sha"][:10], "message": c["commit"]["message"].splitlines()[0],
                         "author": (c.get("author") or {}).get("login")} for c in commits],
            "changed_files": files, "merged_prs": rows, "gaps": gaps}


@mcp.tool(annotations=WRITE)
def create_issue(title: str, body: str, labels: list[str] | None = None) -> dict:
    """Open an issue in the target repo (e.g. one per blocking finding)."""
    issue = gh("POST", "/issues", {"title": title, "body": body, "labels": labels or ["control-coverage"]})
    return {"issue": issue["number"], "url": issue["html_url"]}


@mcp.tool(annotations=WRITE)
def add_controls(files: dict[str, str], title: str, body: str) -> dict:
    """Open a PR that ADDS new files under controls/ (control tests, config). Not gated.
    Refused if any path is outside controls/ or already exists on main: changing or deleting
    existing control files must go through change_controls, which needs human approval."""
    if not files or len(files) > 30:
        raise GitHubError("provide 1-30 files")
    for path in files:
        _check_controls_path(path)
        if _path_exists_on_main(path):
            raise GitHubError(f"refused: {path} already exists on main; use change_controls (needs approval)")
    return _open_pr(_branch_name("controls-add", title), title, body, files)


FIX_FORBIDDEN = re.compile(r"^(controls/|tests/|\.github/)|(^|/)(conftest|testkit)\.py$|pytest\.ini$")


@mcp.tool(annotations=WRITE)
def propose_fix(patch: str, title: str, body: str) -> dict:
    """Open a PR with a fix patch (unified diff, e.g. the fix proven by two_sided.py) to APP code only.
    Refused if the patch touches controls/, tests/, fixtures or CI: a fix may never change the checks
    that judge it. A person reviews and merges the PR; the agent cannot merge."""
    paths = sorted(set(re.findall(r"^(?:\+\+\+|---) (?:a/|b/)?(\S+)", patch, re.M)) - {"/dev/null"})
    if not paths:
        raise GitHubError("refused: patch has no file paths")
    bad = [p for p in paths if FIX_FORBIDDEN.search(p) or ".." in p]
    if bad:
        raise GitHubError(f"refused: a fix may only change app code, not {bad}")
    branch = _branch_name("fix", title)
    with tempfile.TemporaryDirectory() as tmp:
        url = f"https://x-access-token:{TOKEN}@github.com/{REPO}.git"
        def run(*cmd):
            out = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
            if out.returncode != 0:
                raise GitHubError(f"{cmd[1]} failed: {out.stderr.replace(TOKEN, '***')[:300]}")
        run("git", "clone", "-q", "--depth", "1", url, ".")
        run("git", "checkout", "-q", "-b", branch)
        Path(tmp, ".fix.patch").write_text(patch if patch.endswith("\n") else patch + "\n")
        run("git", "apply", ".fix.patch")
        Path(tmp, ".fix.patch").unlink()
        run("git", "-c", "user.name=control-coverage", "-c", "user.email=agent@control-coverage",
            "commit", "-q", "-am", title)
        run("git", "push", "-q", "origin", branch)
    pr = gh("POST", "/pulls", {"title": title, "head": branch, "base": "main",
                               "body": body + "\n\n_Proposed by Control Coverage. Review before merging._"})
    return {"pr": pr["number"], "url": pr["html_url"], "files": paths}


@mcp.tool(annotations=DESTRUCTIVE)
def change_controls(files: dict[str, str], deletions: list[str], reason: str, diff: str) -> dict:
    """Open a PR that MODIFIES or DELETES existing files under controls/. Requires human approval.
    `diff` is shown to the approver: include the exact lines being changed."""
    for path in list(files) + list(deletions):
        _check_controls_path(path)
    body = f"**Reason:** {reason}\n\n```diff\n{diff}\n```"
    return _open_pr(_branch_name("controls-change", reason), f"Change control files: {reason[:60]}",
                    body, files, deletions)


@mcp.tool(annotations=DESTRUCTIVE)
def create_release(tag: str, sha: str, notes_md: str, evidence_md: str, verdict: str,
                   accepted_exceptions: list[str] | None = None) -> dict:
    """Create a git tag and GitHub release. Irreversible: requires human approval.
    Only allowed when verdict.py returned `cleared` or `cleared_with_exceptions`.
    The approver sees: tag, sha, verdict and every accepted exception."""
    if verdict not in ("cleared", "cleared_with_exceptions"):
        raise GitHubError(f"refused: verdict is {verdict!r}; only cleared releases can be published")
    if gh("GET", f"/git/ref/tags/{tag}", ok404=True):
        raise GitHubError(f"refused: tag {tag} already exists")
    status = gh("GET", f"/compare/{sha}...main")["status"]
    if status not in ("ahead", "identical"):
        raise GitHubError(f"refused: {sha} is not on main (compare status {status})")
    release = gh("POST", "/releases", {"tag_name": tag, "target_commitish": sha, "name": tag,
                                       "body": f"{notes_md}\n\n{evidence_md}"})
    return {"release": release["html_url"], "tag": tag, "sha": sha}


if __name__ == "__main__":
    if not REPO or not TOKEN:
        raise SystemExit("set DEMO_REPO and GITHUB_TOKEN in .env")
    print(f"controls-mcp for {REPO} on http://127.0.0.1:{PORT}/mcp")
    mcp.run(transport="streamable-http")
