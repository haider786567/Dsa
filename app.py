#!/usr/bin/env python3
"""Local web interface for the DSA manager.

Run `python3 app.py`, then open http://127.0.0.1:8000 in a browser.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dsa_manager import (
    PROGRESS_FILE,
    QUESTION_FILE,
    REVISION_INTERVALS,
    ensure_question_for_problem,
    find_problem,
    load_progress,
    load_questions,
    question_matches_problem,
    save_question_for_problem,
    run_class_method,
    run_script,
    save_json,
)
from upload import TOPICS, detect_patterns, display_topic, slugify_problem_name, update_readme, upsert_problem


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
TOPIC_FILE = ROOT / ".dsa_topics.json"
GIT_LOCK = threading.Lock()
DIFFICULTIES = {"Easy", "Medium", "Hard"}


def question_for_problem(problem_name: str, questions: list[dict]) -> dict | None:
    return next((question for question in questions if question_matches_problem(question, problem_name)), None)


def git_sync(files: list[Path], message: str) -> str:
    """Commit only this action's files, then push the current branch."""
    relative_files = sorted({path.resolve().relative_to(ROOT).as_posix() for path in files if path.exists()})
    if not relative_files:
        raise ValueError("Nothing was available to commit.")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
        )
        if result.returncode:
            detail = result.stdout.strip() or "Unknown Git error."
            raise ValueError(f"Git sync failed: {detail}")
        return result

    with GIT_LOCK:
        run("git", "add", "--", *relative_files)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", *relative_files], cwd=ROOT, check=False
        )
        if staged.returncode == 0:
            return "No new Git changes to commit."
        if staged.returncode != 1:
            raise ValueError("Git could not inspect the staged changes.")
        # --only prevents unrelated files already staged by the user from being committed.
        run("git", "commit", "--only", "-m", message, "--", *relative_files)
        run("git", "push")
    return "Committed and pushed to GitHub."


def folder_questions() -> list[dict]:
    """Expose every saved topic/difficulty file as a selectable practice card."""
    cards = []
    for topic in topic_options():
        topic_dir = ROOT / topic["directory"]
        for difficulty in DIFFICULTIES:
            level_dir = topic_dir / difficulty
            if not level_dir.is_dir():
                continue
            for solution in sorted(level_dir.glob("*.py")):
                relative_path = solution.relative_to(ROOT).as_posix()
                cards.append(
                    {
                        "id": f"folder:{relative_path}",
                        "title": solution.stem.replace("_", " ").title(),
                        "source_names": [solution.stem],
                        "topic": topic["name"],
                        "difficulty": difficulty,
                        "prompt": f"Re-solve '{solution.stem}' from scratch. Use the original platform statement for the exact requirements, then submit your new solution to replace this saved version.",
                        "constraints": "Use the original problem constraints and aim for the intended time and space complexity.",
                        "edge_cases": ["Smallest valid input", "Boundary values", "Duplicates or repeated state when allowed"],
                        "tests": [],
                        "auto_generated": True,
                        "source_path": relative_path,
                    }
                )
    return cards


def practice_questions() -> list[dict]:
    """Return question-bank cards enriched with their saved folder destination."""
    progress = load_progress()
    cards = []
    covered_paths = set()
    for question in load_questions():
        card = dict(question)
        saved = next((item for item in progress["problems"] if question_matches_problem(question, item["problem"])), None)
        if saved:
            card["source_path"] = saved["path"]
            card["saved_problem"] = saved["problem"]
            covered_paths.add(saved["path"])
        cards.append(card)
    for card in folder_questions():
        if card["source_path"] not in covered_paths:
            cards.append(card)
    return cards


def practice_question(question_id: str) -> dict | None:
    return next((item for item in practice_questions() if item["id"] == question_id), None)


def dashboard_data() -> dict:
    progress = load_progress()
    # Repair any older upload that saved the solution but stopped before its
    # generated revision prompt was written.
    for problem in progress["problems"]:
        ensure_question_for_problem(problem)
    questions = load_questions()
    today = date.today()
    problems = []
    for problem in progress["problems"]:
        item = dict(problem)
        due = date.fromisoformat(item["revision_due"])
        item["days_until_revision"] = (due - today).days
        item["practice_question"] = question_for_problem(item["problem"], questions)
        if item["practice_question"]:
            item["practice_question"] = dict(item["practice_question"], source_path=item["path"], saved_problem=item["problem"])
        problems.append(item)
    problems.sort(key=lambda item: (item["revision_due"], item["problem"]))
    return {
        "today": today.isoformat(),
        "total_solved": len(problems),
        "due_today": sum(item["days_until_revision"] <= 0 for item in problems),
        "topics": len({item.get("topic", "General") for item in problems}),
        "problems": problems,
    }


def topic_options() -> list[dict[str, str]]:
    defaults = [{"directory": directory, "name": display_topic(directory)} for directory in TOPICS.values()]
    custom = json.loads(TOPIC_FILE.read_text(encoding="utf-8")) if TOPIC_FILE.exists() else []
    return defaults + custom


def topic_directory(topic_name: str) -> tuple[str, str]:
    clean_name = topic_name.strip()
    for topic in topic_options():
        if topic["name"].casefold() == clean_name.casefold():
            return topic["directory"], topic["name"]
    if not clean_name or len(clean_name) > 50:
        raise ValueError("Enter a category name between 1 and 50 characters.")
    slug = slugify_problem_name(clean_name).strip("_")
    if not slug:
        raise ValueError("Category name must contain letters or numbers.")
    existing_numbers = [int(item["directory"].split("_", 1)[0]) for item in topic_options() if item["directory"].split("_", 1)[0].isdigit()]
    directory = f"{max(existing_numbers, default=0) + 1:02d}_{slug}"
    custom = json.loads(TOPIC_FILE.read_text(encoding="utf-8")) if TOPIC_FILE.exists() else []
    custom.append({"directory": directory, "name": clean_name})
    save_json(TOPIC_FILE, custom)
    return directory, clean_name


def save_solution(payload: dict) -> dict:
    problem_name = str(payload.get("problem", "")).strip()
    code = str(payload.get("code", ""))
    difficulty = str(payload.get("difficulty", ""))
    question_detail = str(payload.get("question_detail", "")).strip()
    if not problem_name:
        raise ValueError("Enter a problem name.")
    if not code.strip():
        raise ValueError("Paste your Python solution before saving.")
    if difficulty not in DIFFICULTIES:
        raise ValueError("Choose Easy, Medium, or Hard.")

    directory, topic_name = topic_directory(str(payload.get("topic", "")))
    destination = ROOT / directory / difficulty / f"{slugify_problem_name(problem_name)}.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(code.rstrip() + "\n", encoding="utf-8")
    progress = load_progress()
    saved, was_revision = upsert_problem(
        progress,
        {
            "problem": problem_name,
            "topic": topic_name,
            "topic_dir": directory,
            "difficulty": difficulty,
            "path": destination.relative_to(ROOT).as_posix(),
            "patterns": detect_patterns(problem_name, directory, code),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    save_json(PROGRESS_FILE, progress)
    if question_detail:
        prompt_added = True
        generated_question = save_question_for_problem(saved, question_detail, code)
    else:
        prompt_added = ensure_question_for_problem(saved)
        generated_question = next(
            (question for question in load_questions() if question_matches_problem(question, saved["problem"])),
            None,
        )
    update_readme(progress)
    git_message = git_sync(
        [destination, PROGRESS_FILE, QUESTION_FILE, ROOT / "README.md"],
        f"{'Revise' if was_revision else 'Solve'} {problem_name}",
    )
    return {
        "message": f"{'Updated revision' if was_revision else 'Saved solution'} in {destination.relative_to(ROOT)}. {git_message}",
        "prompt_added": prompt_added,
        "test_cases": len(generated_question.get("tests", [])) if generated_question else 0,
        "question": dict(generated_question, source_path=destination.relative_to(ROOT).as_posix(), saved_problem=saved["problem"]) if generated_question else None,
        "dashboard": dashboard_data(),
        "topics": topic_options(),
    }


def submit_practice_solution(payload: dict) -> dict:
    question = practice_question(str(payload.get("question_id", "")))
    code = str(payload.get("code", ""))
    if not question:
        raise ValueError("Unknown practice question. Refresh the page and try again.")
    if not code.strip():
        raise ValueError("Write a Python solution before submitting.")
    if not question.get("source_path"):
        raise ValueError("This question is not linked to a topic folder. Save it using 'Save your progress' above.")

    destination = (ROOT / question["source_path"]).resolve()
    if ROOT not in destination.parents or destination.suffix != ".py":
        raise ValueError("Invalid practice solution path.")
    parts = destination.relative_to(ROOT).parts
    if len(parts) != 3 or parts[1] not in DIFFICULTIES:
        raise ValueError("Practice solutions must be inside Topic/Easy, Medium, or Hard.")
    destination.write_text(code.rstrip() + "\n", encoding="utf-8")

    progress = load_progress()
    problem_name = question.get("saved_problem") or question.get("source_names", [destination.stem])[0]
    saved, was_revision = upsert_problem(
        progress,
        {
            "problem": problem_name,
            "topic": display_topic(parts[0]),
            "topic_dir": parts[0],
            "difficulty": parts[1],
            "path": destination.relative_to(ROOT).as_posix(),
            "patterns": detect_patterns(problem_name, parts[0], code),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    save_json(PROGRESS_FILE, progress)
    ensure_question_for_problem(saved)
    update_readme(progress)
    git_message = git_sync(
        [destination, PROGRESS_FILE, QUESTION_FILE, ROOT / "README.md"],
        f"{'Revise' if was_revision else 'Solve'} {problem_name}",
    )
    return {
        "message": f"Submitted {destination.relative_to(ROOT)}. {git_message}",
        "dashboard": dashboard_data(),
        "questions": practice_questions(),
        "saved_problem": saved["problem"],
    }


def delete_solution(problem_name: str) -> dict:
    progress = load_progress()
    problem = find_problem(progress["problems"], problem_name)
    if not problem:
        raise ValueError("Saved problem not found.")
    solution_path = (ROOT / problem["path"]).resolve()
    if ROOT not in solution_path.parents:
        raise ValueError("Invalid saved solution path.")
    if solution_path.is_file():
        solution_path.unlink()
    progress["problems"] = [item for item in progress["problems"] if item is not problem]
    save_json(PROGRESS_FILE, progress)
    update_readme(progress)

    # Preserve hand-written question cards. Remove only an orphaned generated card.
    remaining = progress["problems"]
    questions = load_questions()
    kept = [
        question
        for question in questions
        if not (
            question.get("auto_generated")
            and question_matches_problem(question, problem["problem"])
            and not any(question_matches_problem(question, item["problem"]) for item in remaining)
        )
    ]
    if len(kept) != len(questions):
        save_json(QUESTION_FILE, kept)
    return {"message": f"Deleted '{problem['problem']}'.", "dashboard": dashboard_data()}


def judge_solution(code: str, question_id: str) -> dict:
    question = practice_question(question_id)
    if not question:
        raise ValueError("Unknown practice question.")
    if not code.strip():
        raise ValueError("Paste your Python solution before running tests.")
    if not question.get("tests"):
        raise ValueError("This folder question has no saved test cases. You can still submit your solution and commit it.")

    results = []
    with tempfile.TemporaryDirectory(prefix="dsa-manager-") as directory:
        candidate = Path(directory) / "solution.py"
        candidate.write_text(code, encoding="utf-8")
        for number, test in enumerate(question.get("tests", []), start=1):
            if question.get("runner", "stdin") == "class_method":
                ok, actual = run_class_method(candidate, question["method"], test.get("args", []))
                expected = test["expected"]
                shown_input = test.get("args", [])
                passed = ok and actual == expected
            else:
                ok, actual = run_script(candidate, test.get("input", ""))
                expected = str(test["expected"]).strip()
                shown_input = test.get("input", "").rstrip("\n")
                passed = ok and actual == expected
            results.append(
                {
                    "number": number,
                    "input": shown_input,
                    "expected": expected,
                    "actual": actual,
                    "passed": passed,
                }
            )
    return {"title": question["title"], "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}


class DSAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/dashboard":
            self.send_json(dashboard_data())
            return
        if path == "/api/questions":
            self.send_json({"questions": practice_questions()})
            return
        if path == "/api/topics":
            self.send_json({"topics": topic_options()})
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            payload = self.read_json()
            if path == "/api/check":
                self.send_json(judge_solution(payload.get("code", ""), payload.get("question_id", "")))
                return
            if path == "/api/mark-revised":
                progress = load_progress()
                problem = find_problem(progress["problems"], payload.get("problem", ""))
                if not problem:
                    raise ValueError("Saved problem not found.")
                count = int(problem.get("revision_count", 0)) + 1
                interval = REVISION_INTERVALS[min(count, len(REVISION_INTERVALS) - 1)]
                problem["revision_count"] = count
                problem["last_revised"] = date.today().isoformat()
                problem["revision_due"] = (date.today() + timedelta(days=interval)).isoformat()
                save_json(PROGRESS_FILE, progress)
                update_readme(progress)
                git_message = git_sync(
                    [PROGRESS_FILE, ROOT / "README.md"], f"Revise {problem['problem']}"
                )
                self.send_json({"message": f"Next revision: {problem['revision_due']}. {git_message}", "dashboard": dashboard_data()})
                return
            if path == "/api/upload":
                self.send_json(save_solution(payload))
                return
            if path == "/api/practice-submit":
                self.send_json(submit_practice_solution(payload))
                return
            if path == "/api/delete-solution":
                self.send_json(delete_solution(payload.get("problem", "")))
                return
            self.send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # keep browser errors readable for a local tool
            self.send_json({"error": f"Unexpected error: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args) -> None:
        print(f"[DSA manager] {format % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DSAHandler)
    print("DSA Manager is running at http://127.0.0.1:8000")
    print("Press Ctrl+C to stop it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDSA Manager stopped.")
    finally:
        server.server_close()
