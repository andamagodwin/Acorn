"""File system tools — read, write, edit, search, navigate."""
import os
import difflib
from pathlib import Path


def read_file(filepath: str, offset: int = 0, limit: int = 0) -> str:
    """Reads a file's contents. Use offset/limit for large files (line numbers, 1-indexed)."""
    try:
        path = Path(filepath).resolve()
        if not path.exists():
            return f"Error: File not found: {filepath}"
        if not path.is_file():
            return f"Error: Not a file: {filepath}"
        if path.stat().st_size > 10_000_000:
            return f"Error: File too large (>10MB). Use offset/limit to read portions."

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if offset or limit:
            start = max(0, offset - 1)
            end = start + limit if limit else len(lines)
            selected = lines[start:end]
            numbered = [f"{i + start + 1}\t{line}" for i, line in enumerate(selected)]
            return f"[{path} lines {start+1}-{min(end, len(lines))} of {len(lines)}]\n" + "".join(numbered)

        numbered = [f"{i+1}\t{line}" for i, line in enumerate(lines)]
        return f"[{path} — {len(lines)} lines]\n" + "".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(filepath: str, content: str) -> str:
    """Creates or overwrites a file with the given content."""
    try:
        path = Path(filepath).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        lines = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
        return f"Success: Wrote {lines} lines to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def edit_file(filepath: str, old_string: str, new_string: str) -> str:
    """Performs a surgical edit — replaces old_string with new_string in the file.
    old_string must be an exact, unique match in the file."""
    try:
        path = Path(filepath).resolve()
        if not path.exists():
            return f"Error: File not found: {filepath}"

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {filepath}. Read the file first to get exact content."
        if count > 1:
            return f"Error: old_string matches {count} locations. Provide more context to make it unique."

        new_content = content.replace(old_string, new_string, 1)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # Show a unified diff of what changed
        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=filepath, tofile=filepath, lineterm='')
        diff_text = "".join(list(diff)[:50])

        return f"Success: Applied edit to {path}\n{diff_text}"
    except Exception as e:
        return f"Error editing file: {e}"


def list_directory(path: str = ".", pattern: str = "") -> str:
    """Lists files and directories. Use pattern for glob filtering (e.g., '*.py')."""
    try:
        dir_path = Path(path).resolve()
        if not dir_path.exists():
            return f"Error: Directory not found: {path}"
        if not dir_path.is_dir():
            return f"Error: Not a directory: {path}"

        if pattern:
            entries = sorted(dir_path.glob(pattern))
        else:
            entries = sorted(dir_path.iterdir())

        if not entries:
            return f"[{dir_path}] — empty" + (f" (pattern: {pattern})" if pattern else "")

        lines = []
        dirs = []
        files = []
        for entry in entries[:200]:  # cap at 200 entries
            if entry.is_dir():
                dirs.append(f"  📁 {entry.name}/")
            else:
                size = entry.stat().st_size
                if size > 1_000_000:
                    size_str = f"{size / 1_000_000:.1f}MB"
                elif size > 1000:
                    size_str = f"{size / 1000:.1f}KB"
                else:
                    size_str = f"{size}B"
                files.append(f"  📄 {entry.name} ({size_str})")

        lines = [f"[{dir_path}]"] + dirs + files
        if len(entries) > 200:
            lines.append(f"  ... and {len(entries) - 200} more entries")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


def search_files(directory: str, query: str, file_pattern: str = "*.py") -> str:
    """Searches file contents for a query string. Returns matching lines with context."""
    try:
        dir_path = Path(directory).resolve()
        if not dir_path.exists():
            return f"Error: Directory not found: {directory}"

        results = []
        files_searched = 0
        max_results = 50

        for filepath in dir_path.rglob(file_pattern):
            if filepath.is_file() and filepath.stat().st_size < 1_000_000:
                files_searched += 1
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel_path = filepath.relative_to(dir_path)
                                results.append(f"  {rel_path}:{line_num}: {line.rstrip()}")
                                if len(results) >= max_results:
                                    break
                except (PermissionError, OSError):
                    continue
            if len(results) >= max_results:
                break

        if not results:
            return f"No matches for '{query}' in {file_pattern} files ({files_searched} files searched)"

        header = f"Found {len(results)} matches for '{query}' ({files_searched} files searched):"
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"Error searching: {e}"
