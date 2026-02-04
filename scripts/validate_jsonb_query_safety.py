"""
SQL Query Safety Validator for JSONB Functions

This script validates that all SQL queries using JSONB functions have proper
type checking to prevent "cannot get array length of a scalar" errors.

Usage:
    python scripts/validate_jsonb_query_safety.py
"""
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict
from dataclasses import dataclass

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class SafetyIssue:
    """Represents a safety issue found in code"""
    file_path: str
    line_number: int
    line_content: str
    issue_type: str
    severity: str
    recommendation: str


class JSONBQuerySafetyValidator:
    """Validates SQL queries for JSONB function safety"""
    
    # Unsafe patterns that need type checking
    UNSAFE_PATTERNS = [
        {
            'pattern': r'jsonb_array_length\s*\([^)]+\)',
            'function': 'jsonb_array_length',
            'required_type': 'array',
            'description': 'jsonb_array_length() requires array type'
        },
        {
            'pattern': r'jsonb_array_elements\s*\([^)]+\)',
            'function': 'jsonb_array_elements',
            'required_type': 'array',
            'description': 'jsonb_array_elements() requires array type'
        },
        {
            'pattern': r'jsonb_object_keys\s*\([^)]+\)',
            'function': 'jsonb_object_keys',
            'required_type': 'object',
            'description': 'jsonb_object_keys() requires object type'
        },
    ]
    
    # Safe patterns (with type checking)
    SAFE_TYPE_CHECK_PATTERN = r'jsonb_typeof\s*\([^)]+\)\s*=\s*[\'"]?array[\'"]?'
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.issues: List[SafetyIssue] = []
    
    def scan_file(self, file_path: Path) -> List[SafetyIssue]:
        """Scan a single file for unsafe JSONB patterns"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")
            return issues
        
        for line_num, line in enumerate(lines, 1):
            # Check each unsafe pattern
            for unsafe_pattern in self.UNSAFE_PATTERNS:
                matches = re.finditer(unsafe_pattern['pattern'], line, re.IGNORECASE)
                for match in matches:
                    # Check if there's a type check before this line or in the same line
                    if not self._has_type_check(lines, line_num, match.start(), unsafe_pattern):
                        issue = SafetyIssue(
                            file_path=str(file_path.relative_to(self.root_dir)),
                            line_number=line_num,
                            line_content=line.strip(),
                            issue_type=f"Unsafe {unsafe_pattern['function']}() call",
                            severity='HIGH',
                            recommendation=(
                                f"Add type check before calling {unsafe_pattern['function']}(): "
                                f"jsonb_typeof(...) = '{unsafe_pattern['required_type']}'"
                            )
                        )
                        issues.append(issue)
        
        return issues
    
    def _has_type_check(self, lines: List[str], current_line: int, match_pos: int, unsafe_pattern: Dict) -> bool:
        """Check if there's a type check before the unsafe function call"""
        # Check current line
        line = lines[current_line - 1]
        
        # Look for type check in the same line before the function call
        before_match = line[:match_pos]
        if re.search(self.SAFE_TYPE_CHECK_PATTERN, before_match, re.IGNORECASE):
            return True
        
        # Check previous lines (within same WHERE clause or condition)
        # Look back up to 5 lines
        for i in range(max(0, current_line - 5), current_line - 1):
            prev_line = lines[i]
            # Check if we're still in the same logical block (WHERE, AND, OR)
            if re.search(r'\b(WHERE|AND|OR)\b', prev_line, re.IGNORECASE):
                if re.search(self.SAFE_TYPE_CHECK_PATTERN, prev_line, re.IGNORECASE):
                    return True
        
        return False
    
    def scan_directory(self, directory: Path, extensions: List[str] = None) -> List[SafetyIssue]:
        """Scan directory for files with unsafe patterns"""
        if extensions is None:
            extensions = ['.py', '.sql']
        
        all_issues = []
        
        for ext in extensions:
            for file_path in directory.rglob(f'*{ext}'):
                # Skip venv and other irrelevant directories
                if 'venv' in str(file_path) or '__pycache__' in str(file_path):
                    continue
                
                issues = self.scan_file(file_path)
                all_issues.extend(issues)
        
        return all_issues
    
    def generate_report(self, issues: List[SafetyIssue]) -> str:
        """Generate a safety report"""
        if not issues:
            return "[SUCCESS] No safety issues found! All JSONB function calls are properly guarded."
        
        report = []
        report.append("=" * 80)
        report.append("JSONB QUERY SAFETY VALIDATION REPORT")
        report.append("=" * 80)
        report.append(f"\nFound {len(issues)} safety issue(s):\n")
        
        # Group by file
        by_file: Dict[str, List[SafetyIssue]] = {}
        for issue in issues:
            if issue.file_path not in by_file:
                by_file[issue.file_path] = []
            by_file[issue.file_path].append(issue)
        
        for file_path, file_issues in sorted(by_file.items()):
            report.append(f"\n[FILE] {file_path}")
            report.append("-" * 80)
            for issue in file_issues:
                report.append(f"  Line {issue.line_number}: {issue.issue_type}")
                report.append(f"    Severity: {issue.severity}")
                report.append(f"    Code: {issue.line_content[:100]}")
                report.append(f"    Fix: {issue.recommendation}")
                report.append("")
        
        report.append("=" * 80)
        report.append("RECOMMENDATIONS:")
        report.append("=" * 80)
        report.append("1. Add jsonb_typeof() checks before all jsonb_array_length() calls")
        report.append("2. Add jsonb_typeof() checks before all jsonb_object_keys() calls")
        report.append("3. Test queries with NULL, JSON null, and wrong type values")
        report.append("4. Use CASE statements for safer evaluation")
        report.append("")
        
        return "\n".join(report)


def main():
    """Main validation function"""
    root_dir = Path(__file__).parent.parent
    validator = JSONBQuerySafetyValidator(root_dir)
    
    print("Scanning codebase for unsafe JSONB patterns...")
    issues = validator.scan_directory(root_dir)
    
    report = validator.generate_report(issues)
    # Use UTF-8 encoding for Windows compatibility
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode('utf-8', errors='replace').decode('utf-8'))
    
    # Exit with error code if issues found
    if issues:
        print(f"\n[ERROR] Found {len(issues)} safety issue(s). Please fix before deploying.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All JSONB queries are safe!")
        sys.exit(0)


if __name__ == "__main__":
    main()

