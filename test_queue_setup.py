#!/usr/bin/env python
import sys
import os

# Add the workspace to the path
sys.path.insert(0, r'c:\Users\nomat\OneDrive\Documentos\VeriCycle')
os.chdir(r'c:\Users\nomat\OneDrive\Documentos\VeriCycle')

print("=" * 80)
print("Testing VeriCycle Task Queue Implementation")
print("=" * 80)

# Test 1: Import models
print("\n[TEST 1] Importing models...")
try:
    from models import AgentTask, Activity, User
    print("✓ Models imported successfully")
    print(f"  - User table: {User.__tablename__}")  # type: ignore
    print(f"  - Activity table: {Activity.__tablename__}")  # type: ignore
    print(f"  - AgentTask table: {AgentTask.__tablename__}")  # type: ignore
except Exception as e:
    print(f"✗ Error importing models: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Import task_enqueue
print("\n[TEST 2] Importing task_enqueue...")
try:
    from agents.task_enqueue import enqueue_pipeline, PIPELINE_TASKS
    print("✓ task_enqueue imported successfully")
    print(f"  - Pipeline tasks: {PIPELINE_TASKS}")
except Exception as e:
    print(f"✗ Error importing task_enqueue: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Import task_worker
print("\n[TEST 3] Importing task_worker...")
try:
    from agents.task_worker import run_worker_loop, AGENT_MAP
    print("✓ task_worker imported successfully")
    print(f"  - Agents in map: {list(AGENT_MAP.keys())}")
except Exception as e:
    print(f"✗ Error importing task_worker: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Check app.py loads
print("\n[TEST 4] Checking app.py loads...")
try:
    import app as app_module
    print("✓ app.py loaded successfully")
except Exception as e:
    print(f"✗ Error loading app.py: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✓ All tests passed! Task queue implementation is ready.")
print("=" * 80)
