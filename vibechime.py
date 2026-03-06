#!/usr/bin/env python3
import subprocess
import re
import time
import sys
import os

POLL_INTERVAL = 0.5
STALE_CYCLES = 4
NUM_LINES = 50
DEBUG = False
LOG_DIR = "./logs"

def get_all_windows():
    script = 'tell application "Terminal" to get name of every window'
    result = subprocess.run(['osascript', '-e', script],
                            capture_output=True, text=True)
    window_names = result.stdout.strip().split(', ')
    return list(enumerate(window_names, start=1))

def get_window_history_by_title(title, num_lines=10):
    script = f'''
    tell application "Terminal"
        repeat with i from 1 to count windows
            if name of window i contains "{title}" then
                return history of window i
            end if
        end repeat
    end tell
    '''
    result = subprocess.run(['osascript', '-e', script],
                            capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')
    return '\n'.join(lines[-num_lines:]) if lines else ""

import re

def normalize_content(text):
    """
    Remove:
    1. Trailing whitespace from each line
    2. Text entered after a '>' prompt (replace with just the marker)
    3. The user input prompt section (between the two separator lines)
    This prevents false notifications from typing/pausing and tab switching.
    """
    lines = text.split('\n')

    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in lines]

    # Clear anything after a prompt marker '>' (preserve the marker itself)
    lines = [re.sub(r'^(.*?>).*', r'\1', line) for line in lines]

    # Find the prompt section boundaries (lines with many dashes)
    separator = '─' * 10
    separator_indices = []
    for i, line in enumerate(lines):
        if separator in line:
            separator_indices.append(i)
    if len(separator_indices) >= 2:
        start_idx = separator_indices[-2]
        end_idx = separator_indices[-1]
        lines = lines[:start_idx] + lines[end_idx+1:]

    return '\n'.join(lines)
  
def bell(title):
    """Fire the bell and log the event"""
    global ts  # ts is set in main loop
    
    if first_bell[title]:
        # Suppress first bell (startup state)
        first_bell[title] = False
        bell_fired[title] = True    
        return
    
    bell_fired[title] = True
    sys.stdout.write('\a')
    sys.stdout.flush()
    print(f"🔔 [{ts}] Idle: {title}")
    write_bell_log(title)

def dbg(msg):
    if DEBUG:
        ts = time.strftime('%H:%M:%S')
        print(f"  [{ts}] {msg}")

def write_bell_log(title):
    """Write diagnostic log showing what triggered the bell"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(LOG_DIR, f"bell_{ts}_{title[:20].replace(' ', '_')}.txt")
    
    # Get fresh 50-line dump at bell time (the "after" state)
    current_dump = get_window_history_by_title(title, num_lines=50)

    with open(filename, 'w') as f:
        f.write(f"BELL FIRED AT:  {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"WINDOW TITLE:   {title}\n")
        f.write(f"STALE COUNT:    {stale_counters[title]} cycles × {POLL_INTERVAL}s = {stale_counters[title] * POLL_INTERVAL}s\n")
        f.write("\n")
        f.write("=" * 70 + "\n")
        f.write("BEFORE (last 50 lines when content last changed):\n")
        f.write("=" * 70 + "\n")
        f.write(last_change_snapshot[title] + "\n")
        f.write("\n")
        f.write("=" * 70 + "\n")
        f.write("AFTER (last 50 lines at bell time):\n")
        f.write("=" * 70 + "\n")
        f.write(current_dump + "\n")

    print(f"   📄 Log written: {filename}")

# Find AI assistant windows by title at startup
windows = get_all_windows()
ai_windows = [(title, idx) for idx, title in windows
              if re.search(r'gemini|claude', title, re.IGNORECASE)]

if not ai_windows:
    print("No Gemini or Claude windows found. Exiting.")
    sys.exit(1)

# Pre-populate state with current content
print(f"👀 Found {len(ai_windows)} window(s), reading initial state...")
window_states          = {title: get_window_history_by_title(title, num_lines=NUM_LINES) for title, _ in ai_windows}
last_change_snapshot   = {title: get_window_history_by_title(title, num_lines=50) for title, _ in ai_windows}
stale_counters         = {title: 0     for title, _ in ai_windows}
bell_fired             = {title: False for title, _ in ai_windows}
first_bell             = {title: True  for title, _ in ai_windows}

startup_time = time.time()

print(f"👀 Monitoring {len(ai_windows)} window(s):")
for title, _ in ai_windows:
    print(f"   • {title}")
print()

ts = None  # Global timestamp variable

while True:
    try:
        ts = time.strftime('%H:%M:%S')
        
        for title, _ in ai_windows:
            current = get_window_history_by_title(title, num_lines=NUM_LINES)
            
            # Compare normalized content (no user input section, no trailing whitespace)
            old_content = normalize_content(window_states[title])
            new_content = normalize_content(current)
            
            if new_content != old_content:
                # Real content changed
                window_states[title] = current

                stale_counters[title] = 0  # RESET stale counter
                bell_fired[title] = False
                
                # Capture 50-line snapshot at this change (for future bell log)
                last_change_snapshot[title] = get_window_history_by_title(title, num_lines=50)
                dbg(f"{title[:30]} CHANGED → reset stale counter")
                              
            else:
                # Nothing changed
                stale_counters[title] += 1
                dbg(f"{title[:30]} same → stale={stale_counters[title]}/{STALE_CYCLES}")
                
                if (stale_counters[title] >= STALE_CYCLES and 
                    not bell_fired[title]):
                    
                    bell(title)                    

        time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nStopped.")
        break