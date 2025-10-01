graph TD;
    A[User Query Input] --> B[System Prompt with DB Schema]
    B --> C{Generate SQL Query};
    C -->|Yes| D[Display Generated SQL];
    D --> E[User Edits Query (optional)];
    E --> F[Execute SQL Query Button];
    F --> G[Run Query Against Database];
    G --> H{Results Found?};
    H -->|Yes| I[Display Results];
    H -->|No| J[Show No Results Message];
    E --> K[User Refines Query (optional)];
    K --> C
