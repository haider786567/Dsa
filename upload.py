import os
import shutil
import subprocess

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
    "17": "17_Trie"
}

print("\n====== DSA Upload Tool ======\n")

print("Topics:")
for k, v in TOPICS.items():
    print(f"{k}. {v}")

topic = input("\nChoose Topic Number: ").strip()

if topic not in TOPICS:
    print("Invalid Topic")
    exit()

difficulty = ""

if topic == "3":
    print("\nDifficulty")
    print("1. Easy")
    print("2. Medium")
    print("3. Hard")

    d = input("Choose: ").strip()

    diff_map = {
        "1": "Easy",
        "2": "Medium",
        "3": "Hard"
    }

    difficulty = diff_map.get(d, "")

problem = input("\nProblem Name: ").strip()

filename = problem.replace(" ", "_") + ".py"

if topic == "3":
    destination = os.path.join(
        TOPICS[topic],
        difficulty,
        filename
    )
else:
    destination = os.path.join(
        TOPICS[topic],
        filename
    )

if not os.path.exists("solution.py"):
    print("\nsolution.py not found!")
    exit()

os.makedirs(os.path.dirname(destination), exist_ok=True)

shutil.copy("solution.py", destination)

print(f"\nSaved to {destination}")

subprocess.run(["git", "add", "."])
subprocess.run(["git", "commit", "-m", f"Solve {problem}"])
subprocess.run(["git", "push"])

print("\nUploaded Successfully 🚀")