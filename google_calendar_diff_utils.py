from datetime import datetime

# Sample structure of old and new events (simplified)
old_events = [
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-15T10:00:00'}, 'end': {'dateTime': '2025-08-15T18:00:00'}},
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-17T07:00:00'}, 'end': {'dateTime': '2025-08-17T16:00:00'}},
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-19T06:00:00'}, 'end': {'dateTime': '2025-08-19T15:00:00'}}
]

new_events = [
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-15T10:00:00'}, 'end': {'dateTime': '2025-08-15T18:00:00'}},  # unchanged
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-17T07:00:00'}, 'end': {'dateTime': '2025-08-17T17:00:00'}},  # updated
    {'summary': "Lowe's 🛠️", 'start': {'dateTime': '2025-08-20T06:00:00'}, 'end': {'dateTime': '2025-08-20T15:00:00'}}   # new
]

def build_diff_notifications(old, new):
    def fmt(dtstr): return datetime.fromisoformat(dtstr).strftime('%Y-%m-%d %H:%M')

    def to_key(event):  # same date, different time = update
        return event['start']['dateTime'][:10]

    old_map = {to_key(e): e for e in old}
    new_map = {to_key(e): e for e in new}

    diffs = []

    for date in new_map:
        if date not in old_map:
            s = fmt(new_map[date]['start']['dateTime'])
            e = fmt(new_map[date]['end']['dateTime'])
            diffs.append(f"➕ New shift on {date} {s}–{e}")
        elif (old_map[date]['start']['dateTime'] != new_map[date]['start']['dateTime'] or
              old_map[date]['end']['dateTime'] != new_map[date]['end']['dateTime']):
            old_s = fmt(old_map[date]['start']['dateTime'])
            old_e = fmt(old_map[date]['end']['dateTime'])
            new_s = fmt(new_map[date]['start']['dateTime'])
            new_e = fmt(new_map[date]['end']['dateTime'])
            diffs.append(f"🔁 Updated shift on {date}: {old_s}–{old_e} → {new_s}–{new_e}")

    for date in old_map:
        if date not in new_map:
            s = fmt(old_map[date]['start']['dateTime'])
            e = fmt(old_map[date]['end']['dateTime'])
            diffs.append(f"❌ Deleted shift on {date} {s}–{e}")

    return diffs

# Generate the diff output
diff_output = build_diff_notifications(old_events, new_events)
diff_output
