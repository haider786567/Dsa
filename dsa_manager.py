#!/usr/bin/env python3
"""A small local DSA revision coach and test-case checker.

All data stays in this repository: `.dsa_progress.json` contains solved
problems and `.dsa_questions.json` contains the practice question bank.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROGRESS_FILE = ROOT / ".dsa_progress.json"
QUESTION_FILE = ROOT / ".dsa_questions.json"
REVISION_INTERVALS = (1, 3, 7, 14, 30)

CONCEPTS = {
    "Basics": {
        "title": "Number fundamentals",
        "review": "Use division by 10 to move through digits. Treat 0, negative inputs, and one-digit values deliberately. For divisibility, stop at √n rather than n when possible.",
        "checklist": [
            "What should happen for 0?",
            "Does the loop terminate for every allowed input?",
            "Can I avoid converting the number to a string if the problem expects arithmetic?",
            "Is my time complexity acceptable for the largest constraint?",
        ],
    },
    "Arrays": {
        "title": "Arrays",
        "review": "State the invariant first: what does each pointer, index, or prefix value mean after every iteration?",
        "checklist": ["Empty array", "One element", "Duplicate values", "Boundary indices"],
    },
    "Strings": {
        "title": "Strings",
        "review": "Be precise about case sensitivity, whitespace, and whether the input can be empty.",
        "checklist": ["Empty string", "One character", "Repeated characters", "Unicode or punctuation if allowed"],
    },
    "Binary Search": {
        "title": "Binary-search invariant",
        "review": "Keep a clear search interval. At every step, discard only values that cannot contain the answer; ensure low and high move past mid so the loop always finishes.",
        "checklist": ["Empty input", "Target at low or high", "Target absent", "Overflow-safe midpoint in fixed-width languages"],
    },
    "Stacks Queues": {
        "title": "Stack and queue discipline",
        "review": "Use a stack for most-recent unmatched state and a queue for first-in-first-out state. Define exactly what an entry represents before pushing it.",
        "checklist": ["Pop from an empty stack", "Leftover state after scanning", "Mismatched pairs", "Repeated operations"],
    },
    "General": {
        "title": "Problem-solving routine",
        "review": "Read constraints before choosing an algorithm. Write down edge cases, then dry-run one normal and one boundary example.",
        "checklist": ["Smallest input", "Largest input", "Duplicates", "Unexpected ordering"],
    },
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid JSON in {path.name}: {error}") from error


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_progress() -> dict[str, Any]:
    progress = load_json(PROGRESS_FILE, {"problems": []})
    progress.setdefault("problems", [])
    return progress


def load_questions() -> list[dict[str, Any]]:
    questions = load_json(QUESTION_FILE, [])
    if not isinstance(questions, list):
        raise SystemExit(".dsa_questions.json must contain a JSON list.")
    return questions


def normalized(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def question_matches_problem(question: dict[str, Any], problem_name: str) -> bool:
    wanted = normalized(problem_name)
    names = [question.get("id", ""), question.get("title", ""), *question.get("source_names", [])]
    return any(wanted == normalized(name) for name in names)


def auto_question(problem: str, topic: str, difficulty: str, patterns: list[str] | None = None) -> dict[str, Any]:
    """Create an honest revision card when only a solution title is known.

    A title alone cannot safely reveal a platform's exact input/output format, so
    generated cards ask the learner to use the original statement for those
    details and still provide topic-aware revision guidance.
    """
    pattern_text = ", ".join(patterns or []) or "general problem solving"
    edges_by_topic = {
        "Arrays": ["Empty or one-element input", "Duplicates", "First and last indices"],
        "Strings": ["Empty input", "One character", "Repeated characters"],
        "Binary Search": ["Empty input", "Target at an endpoint", "Target is absent"],
        "Basics": ["0", "One-digit or smallest input", "Largest permitted value"],
        "Stacks Queues": ["Empty structure", "Unmatched or leftover state", "Repeated operations"],
    }
    slug = re.sub(r"[^a-z0-9]+", "-", problem.lower()).strip("-") or "untitled-problem"
    return {
        "id": slug,
        "title": problem.replace("_", " ").title(),
        "source_names": [problem],
        "topic": topic,
        "difficulty": difficulty,
        "prompt": f"Re-solve '{problem}' from scratch. Use its original platform statement for the exact input and output format. Identify the {pattern_text} approach before writing code.",
        "constraints": "Use the original problem's constraints. Choose an algorithm appropriate for the stated input size; do not rely on only sample inputs.",
        "examples": [],
        "edge_cases": edges_by_topic.get(topic, ["Smallest valid input", "Largest valid input", "Duplicates or repeated state when allowed"]),
        "tests": [],
        "auto_generated": True,
    }


def _statement_heading(line: str) -> tuple[str | None, str]:
    """Return a recognised statement section and any text following its heading."""
    cleaned = line.strip().strip("#").strip()
    # Accept headings copied from Markdown, for example ``**Constraints:**``.
    cleaned = re.sub(r"^[*_`]+|[*_`]+$", "", cleaned).strip()
    match = re.match(r"^(?:problem\s+)?(description|statement|constraints?|examples?)(?:\s*:\s*(.*))?$", cleaned, re.I)
    if match:
        label = match.group(1).lower()
        section = "constraints" if label.startswith("constraint") else "examples" if label.startswith("example") else "description"
        return section, (match.group(2) or "").strip()
    return None, cleaned


def _append_example_part(example: dict[str, Any], kind: str, value: str) -> None:
    if not value:
        return
    existing = str(example.get(kind, ""))
    example[kind] = f"{existing}\n{value}".strip() if existing else value


def _split_top_level(text: str) -> list[str]:
    """Split comma-separated values without breaking lists or quoted strings."""
    parts: list[str] = []
    start = depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _literal_value(value: str) -> Any:
    """Read ordinary Python/JSON literals copied from an example output."""
    try:
        return ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return json.loads(value.strip())


def _class_method_parameters(solution_code: str) -> tuple[str, list[str]] | None:
    """Find a conventional LeetCode-style ``Solution`` method, if present."""
    try:
        tree = ast.parse(solution_code)
    except SyntaxError:
        return None
    solution_class = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Solution"),
        None,
    )
    if not solution_class:
        return None
    method = next(
        (node for node in solution_class.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")),
        None,
    )
    if not method or method.args.vararg or method.args.kwarg:
        return None
    parameters = [argument.arg for argument in [*method.args.posonlyargs, *method.args.args]]
    if parameters and parameters[0] == "self":
        parameters.pop(0)
    return method.name, parameters


def generated_tests_from_examples(examples: list[dict[str, Any]], solution_code: str) -> dict[str, Any]:
    """Create runnable tests from pasted examples when their format is unambiguous."""
    usable = [example for example in examples if example.get("input") and example.get("output")]
    class_method = _class_method_parameters(solution_code)
    if class_method:
        method, parameters = class_method
        tests: list[dict[str, Any]] = []
        for example in usable:
            try:
                assignments = []
                for part in _split_top_level(str(example["input"]).replace("\n", ",")):
                    name, raw_value = part.split("=", 1)
                    assignments.append((name.strip(), _literal_value(raw_value)))
                values_by_name = dict(assignments)
                arguments = (
                    [values_by_name[name] for name in parameters]
                    if all(name in values_by_name for name in parameters)
                    else [value for _, value in assignments] if len(assignments) == len(parameters) else []
                )
                if len(arguments) != len(parameters):
                    continue
                tests.append({"args": arguments, "expected": _literal_value(str(example["output"]))})
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue
        return {"runner": "class_method", "method": method, "tests": tests}

    return {
        "tests": [
            {
                "input": str(example["input"]).rstrip("\n") + "\n",
                "expected": str(example["output"]).strip(),
            }
            for example in usable
        ]
    }


def format_question_detail(question_detail: str, fallback_prompt: str, fallback_constraints: str) -> dict[str, Any]:
    """Split a pasted platform statement into description, constraints, and examples.

    The upload form intentionally accepts ordinary copied text. This recognises
    common headings such as ``Example 1:``, ``Input:``, ``Output:``, and
    ``Constraints:``. Tests are generated separately only when a solution's
    interface and the example values can be read without guesswork.
    """
    description: list[str] = []
    constraints: list[str] = []
    examples: list[dict[str, Any]] = []
    section = "description"
    current_example: dict[str, Any] | None = None

    def start_example(number: str | None = None) -> dict[str, Any]:
        example = {"label": f"Example {number}" if number else f"Example {len(examples) + 1}"}
        examples.append(example)
        return example

    def add_example_line(kind: str, value: str) -> None:
        nonlocal current_example
        if current_example is None:
            current_example = start_example()
        _append_example_part(current_example, kind, value)

    for raw_line in question_detail.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            if section == "description" and description and description[-1] != "":
                description.append("")
            continue

        heading, remainder = _statement_heading(line)
        if heading:
            section = heading
            current_example = None if heading != "examples" else current_example
            if remainder:
                if section == "constraints":
                    constraints.append(remainder)
                elif section == "examples":
                    add_example_line("explanation", remainder)
                else:
                    description.append(remainder)
            continue
        line = remainder

        example_match = re.match(r"^example\s*(\d+)?\s*:\s*(.*)$", line, re.I)
        if example_match:
            section = "examples"
            current_example = start_example(example_match.group(1))
            if example_match.group(2):
                _append_example_part(current_example, "explanation", example_match.group(2).strip())
            continue

        field_match = re.match(r"^(input|output|explanation)\s*:\s*(.*)$", line, re.I)
        if field_match:
            section = "examples"
            add_example_line(field_match.group(1).lower(), field_match.group(2).strip())
            continue

        if section == "constraints":
            constraints.append(line)
        elif section == "examples":
            add_example_line("explanation", line)
        else:
            description.append(line)

    prompt = "\n".join(description).strip() or fallback_prompt
    constraint_text = "\n".join(constraints).strip() or fallback_constraints
    return {"prompt": prompt, "constraints": constraint_text, "examples": examples}


def ensure_question_for_problem(problem: dict[str, Any]) -> bool:
    """Add a generated revision card if a saved solution has no question yet."""
    questions = load_questions()
    if any(question_matches_problem(question, problem["problem"]) for question in questions):
        return False
    questions.append(
        auto_question(
            problem["problem"],
            problem.get("topic", "General"),
            problem.get("difficulty", "Easy"),
            problem.get("patterns", []),
        )
    )
    save_json(QUESTION_FILE, questions)
    return True


def save_question_for_problem(problem: dict[str, Any], question_detail: str, solution_code: str = "") -> dict[str, Any]:
    question = auto_question(
        problem["problem"],
        problem.get("topic", "General"),
        problem.get("difficulty", "Easy"),
        problem.get("patterns", []),
    )
    question.update(format_question_detail(question_detail, question["prompt"], question["constraints"]))
    question.update(generated_tests_from_examples(question["examples"], solution_code))
    question["auto_generated"] = False
    questions = load_questions()
    for index, existing in enumerate(questions):
        if question_matches_problem(existing, problem["problem"]):
            questions[index] = question
            save_json(QUESTION_FILE, questions)
            return question
    questions.append(question)
    save_json(QUESTION_FILE, questions)
    return question


def find_problem(problems: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = normalized(name)
    return next((item for item in problems if normalized(item.get("problem", "")) == wanted), None)


def due_status(problem: dict[str, Any], today: date) -> tuple[int, str]:
    due = date.fromisoformat(problem["revision_due"])
    days = (due - today).days
    if days < 0:
        return days, f"overdue by {-days} day(s)"
    if days == 0:
        return days, "due today"
    return days, f"due in {days} day(s)"


def cmd_dashboard(_: argparse.Namespace) -> None:
    problems = load_progress()["problems"]
    today = date.today()
    due = sorted((item for item in problems if date.fromisoformat(item["revision_due"]) <= today), key=lambda item: item["revision_due"])
    upcoming = sorted((item for item in problems if item not in due and date.fromisoformat(item["revision_due"]) <= today + timedelta(days=7)), key=lambda item: item["revision_due"])
    topics = sorted({item.get("topic", "General") for item in problems})

    print("DSA MANAGER DASHBOARD")
    print(f"Solved: {len(problems)} | Topics: {len(topics)} | Revision due today: {len(due)}")
    if due:
        print("\nDo these first:")
        for item in due:
            _, status = due_status(item, today)
            print(f"  - {item['problem']} ({item.get('topic', 'General')}) — {status}")
    elif upcoming:
        print("\nNothing is due today. Coming up:")
        for item in upcoming[:5]:
            _, status = due_status(item, today)
            print(f"  - {item['problem']} — {status}")
    else:
        print("\nNo scheduled revision in the next 7 days. Add or solve a new question.")


def cmd_revise(args: argparse.Namespace) -> None:
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")
    if args.problem:
        question = next(
            (
                item
                for item in load_questions()
                if question_matches_problem(item, args.problem)
            ),
            None,
        )
        if not question:
            raise SystemExit(
                f"No saved practice prompt for '{args.problem}'. Add it with `add-question`, then try again."
            )
        print("REVISION PRACTICE")
        render_question(question)
        return
    progress = load_progress()
    today = date.today()
    candidates = sorted(
        progress["problems"], key=lambda item: (item.get("revision_due", "9999-12-31"), item.get("problem", ""))
    )
    if args.topic:
        candidates = [item for item in candidates if item.get("topic", "").lower() == args.topic.lower()]
    if not candidates:
        raise SystemExit("No solved problems match that topic yet.")

    selected = candidates[: args.limit]
    topic = selected[0].get("topic", "General") if len({item.get("topic") for item in selected}) == 1 else "General"
    concept = CONCEPTS.get(topic, CONCEPTS["General"])
    print(f"REVISION: {concept['title']}")
    print(concept["review"])
    print("\nBefore coding, ask:")
    for question in concept["checklist"]:
        print(f"  - {question}")
    print("\nYour next revision set:")
    for item in selected:
        _, status = due_status(item, today)
        print(f"  - {item['problem']} [{item.get('difficulty', 'Not set')}] — {status}")
    print("\nAfter you re-solve one, run:")
    print("  python3 dsa_manager.py mark-revised \"Problem Name\"")


def render_question(question: dict[str, Any]) -> None:
    print(f"{question['title']}  |  {question.get('topic', 'General')} · {question.get('difficulty', 'Easy')}")
    print("=" * 72)
    print(question["prompt"])
    print(f"\nConstraints: {question.get('constraints', 'Not specified')}")
    print("Edge cases to handle:")
    for edge_case in question.get("edge_cases", []):
        print(f"  - {edge_case}")
    examples = question.get("examples", [])
    if examples:
        print("Examples:")
        for example in examples:
            print(f"  {example.get('label', 'Example')}")
            for label in ("input", "output", "explanation"):
                if example.get(label):
                    print(f"    {label.title()}: {example[label]}")
    elif tests := question.get("tests", []):
        print("Sample tests:")
        for test in tests[:3]:
            sample_input = test.get("args", test.get("input", ""))
            print(f"  input: {sample_input!r}  → expected: {test.get('expected', '')!r}")
    print("\nWhen ready, put your solution in a .py file and run:")
    print(f"  python3 dsa_manager.py check your_solution.py --question {question['id']}")


def cmd_practice(args: argparse.Namespace) -> None:
    questions = load_questions()
    if args.topic:
        questions = [item for item in questions if item.get("topic", "").lower() == args.topic.lower()]
    if args.difficulty:
        questions = [item for item in questions if item.get("difficulty", "").lower() == args.difficulty.lower()]
    if args.question:
        wanted = normalized(args.question)
        questions = [item for item in questions if normalized(item.get("id", "")) == wanted or normalized(item.get("title", "")) == wanted]
    if not questions:
        raise SystemExit("No matching practice question. Run `python3 dsa_manager.py list-questions` to see choices.")
    # Prefer a question not yet recorded as solved, then use the first stable entry.
    solved = {normalized(item.get("problem", "")) for item in load_progress()["problems"]}
    question = next((item for item in questions if normalized(item["title"]) not in solved), questions[0])
    render_question(question)


def cmd_list_questions(_: argparse.Namespace) -> None:
    for item in load_questions():
        print(f"{item['id']:<18} {item.get('topic', 'General'):<12} {item.get('difficulty', 'Easy'):<8} {item['title']}")


def cmd_add_question(args: argparse.Namespace) -> None:
    """Add a stdin/stdout question so a user's own prompt can be judged."""
    tests: list[dict[str, str]] = []
    for raw_test in args.test:
        try:
            test = json.loads(raw_test)
        except json.JSONDecodeError as error:
            raise SystemExit(f"Each --test must be JSON: {error}") from error
        if not isinstance(test, dict) or "input" not in test or "expected" not in test:
            raise SystemExit('Each --test needs both "input" and "expected" keys.')
        tests.append({"input": str(test["input"]), "expected": str(test["expected"])})

    questions = load_questions()
    if any(item["id"] == args.id for item in questions):
        raise SystemExit(f"A question with id '{args.id}' already exists. Choose a different id.")
    questions.append(
        {
            "id": args.id,
            "title": args.title,
            "topic": args.topic,
            "difficulty": args.difficulty,
            "prompt": args.prompt,
            "constraints": args.constraints,
            "edge_cases": args.edge_case,
            "tests": tests,
        }
    )
    save_json(QUESTION_FILE, questions)
    print(f"Added '{args.title}' with {len(tests)} test case(s).")


def cmd_sync_questions(_: argparse.Namespace) -> None:
    """Create revision prompts for old solutions that pre-date the question bank."""
    added = sum(ensure_question_for_problem(problem) for problem in load_progress()["problems"])
    print(f"Generated {added} missing revision prompt(s).")


def cmd_mark_revised(args: argparse.Namespace) -> None:
    progress = load_progress()
    problem = find_problem(progress["problems"], args.problem)
    if not problem:
        raise SystemExit("Problem not found in .dsa_progress.json. Use the exact problem name shown in dashboard.")
    count = int(problem.get("revision_count", 0)) + 1
    interval = REVISION_INTERVALS[min(count, len(REVISION_INTERVALS) - 1)]
    problem["revision_count"] = count
    problem["last_revised"] = date.today().isoformat()
    problem["revision_due"] = (date.today() + timedelta(days=interval)).isoformat()
    save_json(PROGRESS_FILE, progress)
    # Imported lazily because upload.py also imports the shared DSA helpers.
    from upload import update_readme

    update_readme(progress)
    print(f"Marked '{problem['problem']}' revised. Next review: {problem['revision_due']} ({interval} days).")


def run_script(path: Path, supplied_input: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            input=supplied_input,
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out after 3 seconds. Check for an infinite loop or blocked input."
    if result.returncode != 0:
        return False, (result.stderr.strip() or f"Exited with status {result.returncode}")
    return True, result.stdout.strip()


def run_class_method(path: Path, method: str, arguments: list[Any]) -> tuple[bool, Any]:
    module_name = f"candidate_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        return False, "Could not load this Python file."
    module = importlib.util.module_from_spec(spec)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
        solution = getattr(module, "Solution")()
        return True, getattr(solution, method)(*arguments)
    except Exception as error:  # surface candidate errors as judge output
        return False, f"{type(error).__name__}: {error}"


def cmd_check(args: argparse.Namespace) -> None:
    path = Path(args.file).expanduser().resolve()
    if not path.is_file() or path.suffix != ".py":
        raise SystemExit("Provide an existing Python file, for example: dsa_manager.py check solution.py --question sum-digits")
    questions = load_questions()
    question = next((item for item in questions if item["id"] == args.question), None)
    if not question:
        known = ", ".join(item["id"] for item in questions)
        raise SystemExit(f"Unknown question id '{args.question}'. Available: {known}")

    passed = 0
    tests = question.get("tests", [])
    print(f"Checking {path.name} against: {question['title']}")
    for number, test in enumerate(tests, start=1):
        if question.get("runner", "stdin") == "class_method":
            ok, actual = run_class_method(path, question["method"], test.get("args", []))
            expected = test["expected"]
            matches = ok and actual == expected
            shown_input = test.get("args", [])
        else:
            ok, actual = run_script(path, test.get("input", ""))
            expected = str(test["expected"]).strip()
            matches = ok and actual == expected
            shown_input = test.get("input", "").rstrip("\n")
        if matches:
            passed += 1
            print(f"  PASS {number}: {shown_input!r}")
        else:
            print(f"  FAIL {number}: input {shown_input!r} | expected {expected!r} | got {actual!r}")
    print(f"\nResult: {passed}/{len(tests)} tests passed.")
    if passed != len(tests):
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DSA revision coach and local test-case checker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("dashboard", help="show revision work due today").set_defaults(func=cmd_dashboard)
    revise = commands.add_parser("revise", help="get an automatic concept and revision set")
    revise.add_argument("problem", nargs="?", help="show that problem's full revision prompt, e.g. checkPrime")
    revise.add_argument("--topic", help="limit to a saved topic, e.g. Basics")
    revise.add_argument("--limit", type=int, default=3, help="number of problems to show (default: 3)")
    revise.set_defaults(func=cmd_revise)
    practice = commands.add_parser("practice", help="get a question with constraints and edge cases")
    practice.add_argument("--topic")
    practice.add_argument("--difficulty")
    practice.add_argument("--question", help="question id or title")
    practice.set_defaults(func=cmd_practice)
    commands.add_parser("list-questions", help="list available practice questions").set_defaults(func=cmd_list_questions)
    commands.add_parser("sync-questions", help="generate prompts for saved problems missing one").set_defaults(func=cmd_sync_questions)
    add = commands.add_parser("add-question", help="save your own stdin/stdout practice question and tests")
    add.add_argument("--id", required=True, help="short unique id, e.g. reverse-array")
    add.add_argument("--title", required=True)
    add.add_argument("--topic", default="General")
    add.add_argument("--difficulty", default="Easy", choices=("Easy", "Medium", "Hard"))
    add.add_argument("--prompt", required=True)
    add.add_argument("--constraints", required=True)
    add.add_argument("--edge-case", action="append", default=[], help="repeat for each edge case")
    add.add_argument("--test", action="append", default=[], required=True, help='JSON, e.g. {"input":"5\\n","expected":"5"}')
    add.set_defaults(func=cmd_add_question)
    mark = commands.add_parser("mark-revised", help="schedule the next spaced revision")
    mark.add_argument("problem")
    mark.set_defaults(func=cmd_mark_revised)
    check = commands.add_parser("check", help="run stored tests against your Python solution")
    check.add_argument("file")
    check.add_argument("--question", required=True, help="question id from list-questions")
    check.set_defaults(func=cmd_check)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
