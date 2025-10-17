"""
Quick test to verify playbook update works
"""
import json
from datetime import datetime
from pathlib import Path

playbook_path = Path("./data/playbook.json")

# Load playbook
with open(playbook_path, 'r', encoding='utf-8') as f:
    playbook = json.load(f)

print(f"Before: {playbook['last_updated']}")
print(f"SQL Patterns count: {len(playbook['sections']['sql_patterns'])}")

# Add a test item
new_item = {
    "id": f"test-{len(playbook['sections']['sql_patterns']):05d}",
    "content": "TEST: Use DATE_TRUNC for better month grouping",
    "usage_count": 0,
    "helpful": 0,
    "harmful": 0
}

playbook['sections']['sql_patterns'].append(new_item)
playbook['last_updated'] = datetime.now().isoformat()

# Save
with open(playbook_path, 'w', encoding='utf-8') as f:
    json.dump(playbook, f, indent=2, ensure_ascii=False)

print(f"\nAfter: {playbook['last_updated']}")
print(f"SQL Patterns count: {len(playbook['sections']['sql_patterns'])}")
print(f"New item ID: {new_item['id']}")
print("\n✅ Playbook updated successfully!")
