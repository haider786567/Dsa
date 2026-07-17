import json
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from dsa_manager import QUESTION_FILE, ensure_question_for_problem
from dsa_manager import save_question_for_problem


TOPICS = {
    "1": "01_Basics",
    "2": "02_Sorting",
    "3": "03_Arrays",
    "4": "04_Binary_Search",
    "5": "05_Strings",
    "6": "06_Linked_List",
    "7": "07_Bit_Manipulation",
    "8": "08_Recursion",
    "9": "09_Stacks_Queues",
    "10": "10_Sliding_Window",
    "11": "11_Greedy",
    "12": "12_Binary_Trees",
    "13": "13_BST",
    "14": "14_Heap",
    "15": "15_Graph",
    "16": "16_DP",
    "17": "17_Trie",
}

DIFFICULTIES = {
    "1": "Easy",
    "2": "Medium",
    "3": "Hard",
}

PROGRESS_FILE = Path(".dsa_progress.json")
README_FILE = Path("README.md")
SOLUTION_FILE = Path("solution.py")

PATTERN_MATCHERS = {
    "Two Pointers": ["two pointer", "two-pointer", "left", "right", "l =", "r ="],
    "Sliding Window": ["window", "sliding", "left", "right"],
    "Binary Search": ["binary search", "mid", "low", "high"],
    "Prefix Sum": ["prefix", "cumulative", "running sum"],
    "Hashing": ["hash", "dict", "set(", "map", "frequency", "counter"],
    "Sorting": ["sort", "sorted"],
    "Stack": ["stack", "append", "pop"],
    "Queue": ["queue", "deque", "popleft"],
    "Recursion": ["recursion", "recursive", "dfs", "backtrack"],
    "Dynamic Programming": ["dp", "memo", "tabulation"],
    "Greedy": ["greedy"],
    "Graph Traversal": ["graph", "bfs", "dfs", "visited", "adj"],
    "Tree Traversal": ["tree", "root", "inorder", "preorder", "postorder"],
    "Bit Manipulation": ["bit", "xor", "&", "|", "<<", ">>"],
    "String Matching": ["substring", "pattern", "kmp", "match"],
    "Math": ["digit", "mod", "%", "gcd", "prime"],
}


def slugify_problem_name(problem):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", problem.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "Untitled_Problem"


def display_topic(topic_dir):
    return topic_dir.split("_", 1)[1].replace("_", " ")


def detect_patterns(problem, topic_dir, code):
    search_text = f"{problem} {topic_dir} {code}".lower()
    matches = []

    for pattern, hints in PATTERN_MATCHERS.items():
        if any(hint.lower() in search_text for hint in hints):
            matches.append(pattern)

    topic_name = display_topic(topic_dir)
    topic_pattern_map = {
        "Binary Search": "Binary Search",
        "Sliding Window": "Sliding Window",
        "Greedy": "Greedy",
        "Graph": "Graph Traversal",
        "DP": "Dynamic Programming",
        "Bit Manipulation": "Bit Manipulation",
        "Strings": "String Matching",
        "Sorting": "Sorting",
        "Stacks Queues": "Stack",
        "Binary Trees": "Tree Traversal",
        "BST": "Tree Traversal",
    }

    topic_pattern = topic_pattern_map.get(topic_name)
    if topic_pattern and topic_pattern not in matches:
        matches.insert(0, topic_pattern)

    return matches or ["General Problem Solving"]


def revision_due_date(revision_count):
    intervals = [1, 3, 7, 14, 30]
    days = intervals[min(revision_count, len(intervals) - 1)]
    return date.today() + timedelta(days=days)


def load_progress():
    if not PROGRESS_FILE.exists():
        return {"problems": []}

    with PROGRESS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_progress(progress):
    with PROGRESS_FILE.open("w", encoding="utf-8") as file:
        json.dump(progress, file, indent=2)
        file.write("\n")


def upsert_problem(progress, problem_data):
    for existing in progress["problems"]:
        if existing["path"] == problem_data["path"]:
            existing.update(problem_data)
            existing["revision_count"] = existing.get("revision_count", 0) + 1
            existing["revision_due"] = revision_due_date(existing["revision_count"]).isoformat()
            existing["last_revised"] = date.today().isoformat()
            return existing, True

    problem_data["revision_count"] = 0
    problem_data["revision_due"] = revision_due_date(0).isoformat()
    problem_data["last_revised"] = None
    progress["problems"].append(problem_data)
    return problem_data, False


def markdown_link(path):
    return path.replace(" ", "%20")


def progress_bar(done, total, width=20):
    if total == 0:
        return "`[--------------------] 0%`"

    filled = round((done / total) * width)
    bar = "#" * filled + "-" * (width - filled)
    percent = round((done / total) * 100)
    return f"`[{bar}] {percent}%`"


def count_by_key(items, key):
    counts = {}
    for item in items:
        value = item.get(key) or "Not Set"
        counts[value] = counts.get(value, 0) + 1
    return counts


def readme_table(rows, empty_message):
    if not rows:
        return empty_message
    return "\n".join(rows)


def build_readme(progress):
    problems = sorted(
        progress["problems"],
        key=lambda item: (item.get("updated_at", ""), item.get("problem", "")),
        reverse=True,
    )
    total = len(problems)
    today = date.today()

    topic_counts = count_by_key(problems, "topic")
    difficulty_counts = count_by_key(problems, "difficulty")
    pattern_counts = {}
    for problem in problems:
        for pattern in problem.get("patterns", []):
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

    revision_items = sorted(
        problems,
        key=lambda item: item.get("revision_due", "9999-12-31"),
    )

    revision_rows = []
    for item in revision_items:
        due = datetime.strptime(item["revision_due"], "%Y-%m-%d").date()
        days = (due - today).days
        if days < 0:
            status = f"Overdue by {-days} day(s)"
        elif days == 0:
            status = "Due today"
        else:
            status = f"Due in {days} day(s)"
        last_revised = item.get("last_revised")
        if not last_revised:
            last_revised = "Not revised yet" if item.get("revision_count", 0) == 0 else "Before tracking"
        revision_rows.append(
            f"| {item['problem']} | {item['topic']} | {item.get('revision_count', 0)} | {last_revised} | {item['revision_due']} | {status} |"
        )

    topic_rows = [
        f"| {topic} | {topic_counts.get(topic, 0)} | {progress_bar(topic_counts.get(topic, 0), total)} |"
        for topic in sorted(topic_counts)
    ]

    difficulty_rows = [
        f"| {difficulty} | {count} |"
        for difficulty, count in sorted(difficulty_counts.items())
    ]

    pattern_rows = [
        f"| {pattern} | {count} |"
        for pattern, count in sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    recent_rows = [
        f"| [{item['problem']}]({markdown_link(item['path'])}) | {item['topic']} | {item['difficulty']} | {', '.join(item['patterns'])} | {item['updated_at'][:10]} |"
        for item in problems[:10]
    ]

    return f"""# DSA Progress

Auto-updated by `upload.py`.

## Summary

| Metric | Value |
| --- | ---: |
| Problems solved | {total} |
| Topics touched | {len(topic_counts)} |
| Patterns identified | {len(pattern_counts)} |
| Last updated | {datetime.now().strftime("%Y-%m-%d %H:%M")} |

## Topic Progress

| Topic | Solved | Progress |
| --- | ---: | --- |
{readme_table(topic_rows, "| No topics yet | 0 | `[--------------------] 0%` |")}

## Difficulty

| Difficulty | Solved |
| --- | ---: |
{readme_table(difficulty_rows, "| Not Set | 0 |")}

## Pattern Matching

| Pattern | Problems |
| --- | ---: |
{readme_table(pattern_rows, "| No patterns yet | 0 |")}

## Revision Tracker

Every saved problem appears here. This table is regenerated whenever you submit or mark a solution as revised.

| Problem | Topic | Revisions | Last Revised | Next Revision | Status |
| --- | --- | ---: | --- | --- | --- |
{readme_table(revision_rows, "| No saved problems yet | - | 0 | - | - | - |")}

## Recently Solved

| Problem | Topic | Difficulty | Pattern(s) | Updated |
| --- | --- | --- | --- | --- |
{readme_table(recent_rows, "| No problems added yet | - | - | - | - |")}
"""


def update_readme(progress):
    README_FILE.write_text(build_readme(progress), encoding="utf-8")


def run_git_command(args):
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        command = " ".join(args)
        raise SystemExit(f"\nCommand failed: {command}")


def choose_topic():
    print("Topics:")
    for key, value in TOPICS.items():
        print(f"{key}. {value}")

    topic = input("\nChoose Topic Number: ").strip()
    if topic not in TOPICS:
        raise SystemExit("Invalid Topic")

    return topic


def choose_difficulty():
    print("\nDifficulty")
    for key, value in DIFFICULTIES.items():
        print(f"{key}. {value}")

    difficulty = DIFFICULTIES.get(input("Choose: ").strip())
    if not difficulty:
        raise SystemExit("Invalid Difficulty")

    return difficulty


def main():
    print("\n====== DSA Upload Tool ======\n")

    topic = choose_topic()
    difficulty = choose_difficulty()
    problem = input("\nProblem Name: ").strip()
    if not problem:
        raise SystemExit("Problem name is required")
    question_detail = input("\nQuestion Details (optional): ").strip()

    if not SOLUTION_FILE.exists():
        raise SystemExit("\nsolution.py not found!")

    filename = f"{slugify_problem_name(problem)}.py"
    topic_dir = TOPICS[topic]
    destination = Path(topic_dir) / difficulty / filename

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOLUTION_FILE, destination)

    code = SOLUTION_FILE.read_text(encoding="utf-8")
    now = datetime.now().isoformat(timespec="seconds")
    progress = load_progress()
    saved_problem, was_revision = upsert_problem(
        progress,
        {
            "problem": problem,
            "topic": display_topic(topic_dir),
            "topic_dir": topic_dir,
            "difficulty": difficulty,
            "path": destination.as_posix(),
            "patterns": detect_patterns(problem, topic_dir, code),
            "updated_at": now,
        },
    )

    save_progress(progress)
    if question_detail:
        save_question_for_problem(saved_problem, question_detail)
        question_added = True
    else:
        question_added = ensure_question_for_problem(saved_problem)
    update_readme(progress)

    print(f"\nSaved to {destination}")
    print(f"Pattern match: {', '.join(saved_problem['patterns'])}")
    print(f"Revision due: {saved_problem['revision_due']}")
    if question_added:
        print("Generated a revision prompt for this question.")

    files_to_stage = [
        destination.as_posix(),
        PROGRESS_FILE.as_posix(),
        QUESTION_FILE.as_posix(),
        README_FILE.as_posix(),
    ]
    run_git_command(["git", "add", *files_to_stage])

    action = "Revise" if was_revision else "Solve"
    run_git_command(["git", "commit", "-m", f"{action} {problem}"])
    run_git_command(["git", "push"])

    print("\nUploaded Successfully")


if __name__ == "__main__":
    main()
