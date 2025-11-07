# This script is used to count the lines of code in the project. I love watching the numbers go up.
import os

# Current lines of code count: 43321 11/06/2025

def count_lines(path, extensions=None, ignore_dirs=None):
    total_lines = 0
    for root, dirs, files in os.walk(path):
        # remove ignored folders from traversal
        if ignore_dirs:
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for file in files:
            if extensions is None or any(file.endswith(ext) for ext in extensions):
                if file == "__init__.py":  # skip if you want
                    print(f"Skipping {os.path.join(root, file)} (ignored)")
                    continue

                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        file_line_count = len(lines)
                        total_lines += file_line_count
                        print(f"Checked {file_path} → {file_line_count} lines")
                except Exception as e:
                    print(f"Skipping {file_path}: {e}")
    return total_lines


if __name__ == "__main__":
    project_path = "."  # current folder
    extensions = [".py", ".js", ".html", ".css"]  
    ignore_dirs = ["venvs", "venv", "__pycache__", "generated_apis"]  
    lines = count_lines(project_path, extensions, ignore_dirs)
    print("="*50)
    print(f"✅ Total lines of code: {lines}")
