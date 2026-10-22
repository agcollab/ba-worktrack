# BA WorkTrack: database ER diagram

GitHub draws this diagram automatically when you open the file on github.com.
In VS Code, install the "Markdown Preview Mermaid Support" extension and press Ctrl+Shift+V.

How to read the lines: `||--o{` means "one ... to zero or more". For example, one
TASK has zero or more TIME_ENTRIES, and each time entry belongs to exactly one task.
`created_at` / `updated_at` columns are left out to keep the picture readable.

```mermaid
erDiagram
    USERS ||--o{ USER_ROLES : has
    ROLES ||--o{ USER_ROLES : "given to"
    USERS ||--o{ PROJECT_MEMBERS : "works on"
    PROJECTS ||--o{ PROJECT_MEMBERS : has
    USERS |o--o{ PROJECTS : owns
    PROJECTS ||--o{ TASKS : contains
    USERS |o--o{ TASKS : "assigned to"
    TASKS ||--o{ TASK_STATUS_HISTORY : "status changes"
    TASKS ||--o{ TASK_COMMENTS : has
    TASKS ||--o{ ATTACHMENTS : has
    TASKS ||--o{ TIME_ENTRIES : "hours logged on"
    USERS ||--o{ TIME_ENTRIES : logs
    PROJECTS ||--o{ REQUIREMENTS : has
    TASKS |o--o{ REQUIREMENTS : "produces"
    REQUIREMENTS ||--o{ ACCEPTANCE_CRITERIA : has
    REQUIREMENTS ||--o{ TEST_CASES : "tested by"
    USERS |o--o{ AI_GENERATION_LOGS : requests
    TASKS |o--o{ AI_GENERATION_LOGS : "about"
    PROJECTS |o--o{ INTEGRATIONS : "synced with"
    INTEGRATIONS ||--o{ INTEGRATION_MAPPINGS : has
    USERS |o--o{ AUDIT_LOGS : "did"
    USERS ||--o| RUNNING_TIMERS : "runs"
    TASKS ||--o{ RUNNING_TIMERS : "timed by"
    INTEGRATIONS |o--o{ TASKS : "imported"
    INTEGRATIONS ||--o{ SYNC_LOGS : "sync history"
    PROJECTS |o--o{ GENERATED_REPORTS : "reported in"

    USERS {
        int id PK
        string email UK
        string full_name
        string hashed_password
        bool is_active
        string job_title
        float weekly_capacity_hours
        int failed_logins
        datetime locked_until
        datetime last_login_at
        bool must_change_password
    }
    ROLES {
        int id PK
        string name UK "Admin, PM, BA"
        string description
    }
    USER_ROLES {
        int user_id PK, FK
        int role_id PK, FK
    }
    PROJECTS {
        int id PK
        string key UK "e.g. PAY"
        string name UK
        text description
        int owner_id FK
        date start_date
        date end_date
        bool is_active
    }
    PROJECT_MEMBERS {
        int id PK
        int project_id FK
        int user_id FK
        string role_in_project
        datetime joined_at
    }
    TASKS {
        int id PK
        string title
        text description
        string status "To Do, In Progress, In Review, Done"
        string priority "Low, Medium, High, Critical"
        string task_type "Requirements, UAC, Testing, Meeting, Analysis, Other"
        float estimate_hours
        date due_date
        int project_id FK
        int assignee_id FK
        int created_by_id FK
        string external_source "jira or ado"
        string external_id
        string external_url
        int integration_id FK
        string external_status "last status seen remotely"
        string synced_status "local status at last sync"
        datetime synced_at
    }
    TASK_STATUS_HISTORY {
        int id PK
        int task_id FK
        string from_status
        string to_status
        int changed_by_id FK
        datetime changed_at
    }
    TASK_COMMENTS {
        int id PK
        int task_id FK
        int author_id FK
        text body
    }
    ATTACHMENTS {
        int id PK
        int task_id FK
        int uploaded_by_id FK
        string filename
        string stored_path
        string content_type
        int size_bytes
    }
    TIME_ENTRIES {
        int id PK
        int user_id FK
        int task_id FK
        date work_date
        float hours "CHECK 0 < hours <= 24"
        string note
    }
    REQUIREMENTS {
        int id PK
        int project_id FK
        int task_id FK
        string title
        text description
        string kind
        string status
        string source "Manual or AI"
        int created_by_id FK
    }
    ACCEPTANCE_CRITERIA {
        int id PK
        int requirement_id FK
        int position
        text given_text
        text when_text
        text then_text
    }
    TEST_CASES {
        int id PK
        int requirement_id FK
        string title
        text preconditions
        text steps
        text expected_result
        string priority
        string status "Not Run, Passed, Failed, Blocked"
    }
    AI_GENERATION_LOGS {
        int id PK
        int user_id FK
        int task_id FK
        string feature
        string model_name
        string prompt_version
        text prompt
        text response
        int duration_ms
        bool success
        text error_message
        string outcome "accepted, edited, rejected"
    }
    INTEGRATIONS {
        int id PK
        string name UK
        string kind "jira or ado"
        string base_url
        string remote_project
        string username
        text encrypted_token "Fernet-encrypted"
        text config_json "conflict policy, JQL / WIQL filters"
        int local_project_id FK
        bool is_enabled
        bool auto_sync
        datetime last_sync_at
        string last_sync_status
        text last_sync_message
    }
    INTEGRATION_MAPPINGS {
        int id PK
        int integration_id FK
        string field
        string local_value
        string remote_value
    }
    AUDIT_LOGS {
        int id PK
        int user_id FK
        string action
        string entity_type
        int entity_id
        text details
        string ip_address
        datetime created_at
    }
    RUNNING_TIMERS {
        int id PK
        int user_id FK, UK "one timer per user"
        int task_id FK
        datetime started_at
        string note
    }
    SYNC_LOGS {
        int id PK
        int integration_id FK
        string action "import, sync, push, test"
        string status "ok, partial, error"
        int items_processed
        int items_created
        int items_updated
        int conflicts
        text message
        int triggered_by_id FK
        datetime created_at
    }
    GENERATED_REPORTS {
        int id PK
        string kind "weekly"
        string title
        date period_start
        date period_end
        int project_id FK
        binary pdf_data
        binary xlsx_data
        int created_by_id FK
        datetime created_at
    }
```
