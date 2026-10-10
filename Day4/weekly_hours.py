import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "practice.db"

conn = sqlite3.connect(DB)
rows = conn.execute(
    """
    SELECT u.name, strftime('%Y-%W', te.work_date) AS week, SUM(te.hours) AS total
    FROM time_entries te
    JOIN users u ON u.id = te.user_id
    WHERE te.hours > ?
    GROUP BY u.name, week
    ORDER BY week, total DESC
    """,
    (0,),                       # values go in separately, never glued into the string
).fetchall()
conn.close()

for name, week, total in rows:
    flag = "  ⚠ over 40" if total > 40 else ""
    print(f"{week}  {name:<6} {total:>5.1f} h{flag}")