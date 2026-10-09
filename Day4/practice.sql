-- =====================================================================
-- BA WorkTrack – Day 4 SQL crash course
-- Open in DB Browser for SQLite → Execute SQL. Run PART A once (F5),
-- then write each exercise under its heading and run just that query
-- (select the lines, Ctrl+Return).
-- =====================================================================

-- ---------------------------------------------------------------------
-- PART A: setup (S1 + S4). Safe to re-run: it drops and rebuilds.
-- ---------------------------------------------------------------------
PRAGMA foreign_keys = ON;   -- SQLite ignores REFERENCES unless this is on

DROP TABLE IF EXISTS user_roles;   -- created in S7
DROP TABLE IF EXISTS roles;        -- created in S7
DROP TABLE IF EXISTS time_entries;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id    INTEGER PRIMARY KEY,          -- unique row number, auto-assigned
    name  TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL           -- no two users share an email
);

CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'To Do'
                CHECK (status IN ('To Do', 'In Progress', 'Done')),
    assignee_id INTEGER REFERENCES users(id),   -- foreign key: must be a real user (or NULL)
    due_date    DATE,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE time_entries (
    id        INTEGER PRIMARY KEY,
    task_id   INTEGER NOT NULL REFERENCES tasks(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    work_date DATE NOT NULL,
    hours     REAL NOT NULL CHECK (hours > 0 AND hours <= 24)
);

-- ---------------------------------------------------------------------
-- PART B: sample data (S2). 3 users, 8 tasks, 2 weeks of time entries.
-- ---------------------------------------------------------------------
INSERT INTO users (name, email) VALUES
    ('Asha', 'asha@example.com'),
    ('Ben',  'ben@example.com'),
    ('Chen', 'chen@example.com');

INSERT INTO tasks (title, status, assignee_id, due_date, created_at) VALUES
    ('Write UAC for login',        'In Progress', 1, '2026-10-20', '2026-10-01 09:00'),
    ('Gap analysis: billing',      'To Do',       2, '2026-10-25', '2026-10-02 10:30'),
    ('Draft BRD: checkout',        'Done',        1, '2026-10-10', '2026-10-03 11:00'),
    ('UAT test cases: payments',   'In Progress', 3, '2026-10-22', '2026-10-05 14:00'),
    ('Process map: refunds',       'To Do',       3, '2026-10-30', '2026-10-06 09:15'),
    ('Stakeholder interviews',     'In Progress', 2, '2026-10-18', '2026-10-07 16:45'),
    ('Data dictionary: orders',    'To Do',       NULL, '2026-11-02', '2026-10-08 08:30'),
    ('Review user stories sprint', 'Done',        1, '2026-10-12', '2026-10-09 13:20');

INSERT INTO time_entries (task_id, user_id, work_date, hours) VALUES
    -- week of Mon 12 Oct
    (1, 1, '2026-10-12', 9.0), (1, 1, '2026-10-13', 9.0), (8, 1, '2026-10-14', 9.0),
    (1, 1, '2026-10-15', 8.0), (1, 1, '2026-10-16', 8.0),
    (6, 2, '2026-10-12', 6.0), (6, 2, '2026-10-13', 7.5), (2, 2, '2026-10-14', 8.0),
    (6, 2, '2026-10-15', 6.5),
    (4, 3, '2026-10-13', 5.0), (4, 3, '2026-10-14', 6.0), (5, 3, '2026-10-16', 4.0),
    -- week of Mon 19 Oct
    (1, 1, '2026-10-19', 6.0), (1, 1, '2026-10-20', 7.0),
    (2, 2, '2026-10-19', 8.0), (2, 2, '2026-10-21', 5.5),
    (4, 3, '2026-10-20', 7.0), (4, 3, '2026-10-21', 7.5), (4, 3, '2026-10-22', 6.0);


-- =====================================================================
-- EXERCISES – write your query under each line, run it, check the hint.
-- =====================================================================

-- S2-a  List all tasks that are NOT Done, newest first (by created_at).
--       Hint: 6 rows, first one is "Data dictionary: orders".


-- S2-b  Show only the 3 tasks due soonest (due_date ascending, LIMIT).


-- S3-a  Move "Gap analysis: billing" to 'In Progress'. ALWAYS use WHERE.
--       Then SELECT it to check.


-- S3-b  Insert a throwaway task called 'TEST – delete me', then DELETE it
--       (WHERE id = ...). Check with SELECT COUNT(*) FROM tasks;  → 8


-- S4    Try to break the foreign key: insert a time entry for task_id 99.
--       You should get "FOREIGN KEY constraint failed". Then try hours = 30
--       and read the CHECK error. Write in a comment why both are good.


-- S5-a  INNER JOIN: every time entry with task title and user name.
--       Columns: work_date, name, title, hours.  → 19 rows


-- S5-b  LEFT JOIN: every task with its assignee name, including the one
--       nobody is assigned to (name shows NULL).  → 8 rows


-- S6-a  Total hours per user (SUM + GROUP BY), highest first.
--       Hint: Asha 56.0, Ben 41.5, Chen 35.5


-- S6-b  Hours per user per week. Use strftime('%Y-%W', work_date) AS week.


-- S6-c  Users with more than 40 hours in a single week (HAVING).
--       → just Asha, week of 12 Oct, 43.0


-- S6-d  Number of tasks and average hours logged per task status
--       (COUNT, AVG, LEFT JOIN so tasks with no hours still count).


-- S7-a  Many-to-many: create roles (id, name) and user_roles
--       (user_id, role_id, PRIMARY KEY (user_id, role_id)).
--       Add roles BA, PM, Admin. Make Asha BA+Admin, Ben BA, Chen PM.
--       Then list each user with their roles.


-- S7-b  CREATE INDEX idx_tasks_status ON tasks(status);
--       Then run:  EXPLAIN QUERY PLAN SELECT * FROM tasks WHERE status = 'To Do';
--       and look for "USING INDEX".
