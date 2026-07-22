#!/usr/bin/env python3
"""
Task mapping between TASK-NNN references and Plane.so issue IDs.
Stored as a JSON file for persistence across bridge restarts.
"""
import json, os, re
from pathlib import Path

TASK_MAP_PATH = Path(os.path.dirname(os.path.abspath(__file__))) / 'task_map.json'

def load_task_map():
    """Load the TASK-NNN to Plane issue mapping."""
    if TASK_MAP_PATH.exists():
        with open(TASK_MAP_PATH) as f:
            return json.load(f)
    return {}

def save_task_map(task_map):
    """Save the task mapping to disk."""
    with open(TASK_MAP_PATH, 'w') as f:
        json.dump(task_map, f, indent=2)

def get_task(task_id):
    """Get plane issue info for a TASK-NNN reference."""
    mapping = load_task_map()
    return mapping.get(task_id)

def set_task(task_id, plane_issue_id, sequence_id, url, name=""):
    """Store a TASK-NNN → Plane issue mapping."""
    mapping = load_task_map()
    mapping[task_id] = {
        "plane_issue_id": plane_issue_id,
        "sequence_id": sequence_id,
        "url": url,
        "name": name,
    }
    save_task_map(mapping)

def next_task_number():
    """Get the next available task number."""
    mapping = load_task_map()
    if not mapping:
        return 1
    numbers = []
    for key in mapping:
        try:
            numbers.append(int(key.replace('TASK-', '')))
        except ValueError:
            pass
    return (max(numbers) + 1) if numbers else 1

def task_exists(task_id):
    """Check if a TASK-NNN already exists in the mapping."""
    mapping = load_task_map()
    return task_id in mapping

def guess_task_reference(text):
    """Extract a TASK-NNN reference from text, or return None."""
    match = re.search(r'TASK[-\s]?(\d+)', text, re.IGNORECASE)
    if match:
        return f'TASK-{match.group(1)}'
    return None

def find_status_in_text(text):
    """
    Find a status keyword in text and return the matching Plane.so state key.
    
    Priority:
    1. "Status: X" or "State: X" explicit patterns
    2. Longest multi-word keyword match (avoids "ready" matching in "ready for review")
    3. Single-word keyword match at word boundaries
    """
    from plane_api import STATUS_MAP
    text_lower = text.lower()
    
    # ── Step 1: Check explicit "Status: X" patterns ──
    explicit = re.search(
        r'(?:status|state)\s*:?\s*:\s*([^\n\r]{1,40})',
        text_lower
    )
    if explicit:
        status_val = explicit.group(1).strip().rstrip('.')
        # Try to match the explicit status value against STATUS_MAP
        best_key, best_len = None, 0
        for key in STATUS_MAP:
            if re.search(r'\b' + re.escape(key) + r'\b', status_val):
                if len(key) > best_len:
                    best_key, best_len = key, len(key)
        if best_key:
            return best_key
    
    # ── Step 2: Sort STATUS_MAP keys by length (longest first) ──
    sorted_keys = sorted(STATUS_MAP.keys(), key=len, reverse=True)
    
    # Build patterns from STATUS_MAP keys in priority order
    for key in sorted_keys:
        # Use word boundary for all patterns
        pattern = r'\b' + re.escape(key) + r'\b'
        if re.search(pattern, text_lower):
            return key
    
    return None
