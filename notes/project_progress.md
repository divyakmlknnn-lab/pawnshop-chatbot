# LocalBank Teller Assistant Progress

## Completed
- Installed Python
- Installed MySQL + Workbench
- Created local_bank database
- Created customers, loans, payments tables
- Inserted sample banking data
- Built SQL calculations for:
  - Loan-to-value
  - Remaining due
- Connected Python backend to MySQL
- Built Flask API routes
- Built chatbot route
- Built frontend chatbot UI
- Connected frontend to backend successfully

## Current Architecture
Frontend (HTML/CSS/JS)
↓
Flask Backend API
↓
MySQL Database

## MCP Safe SQL (POC)

Validation-only MCP server package: `backend/pawnshop_mcp/`

- Server name: `Pawnshop Chatbot`
- Transport: stdio
- Resource: `pawnshop://schema/approved` (approved schema JSON)
- Tool: `validate_safe_sql` (wraps `validate_readonly_sql`, no SQL execution)

Run locally:

```bash
cd backend
python3 -m pawnshop_mcp
```

### Cursor MCP configuration

Add this to your user-level Cursor MCP settings (do not commit machine-specific paths into the repo):

```json
{
  "mcpServers": {
    "Pawnshop Chatbot": {
      "command": "python3",
      "args": ["-m", "pawnshop_mcp"],
      "cwd": "<project-root>/backend"
    }
  }
}
```

Replace "<project-root>" with the absolute path to your local project directory.