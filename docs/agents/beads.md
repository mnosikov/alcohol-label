# Beads Workflow

This project uses Beads for local build traceability during implementation. GitHub is the source of truth for commits, and GitHub Actions is the source of truth for CI and deployment.

Common commands:

```bash
bd list
bd show <issue-id>
bd update <issue-id> --claim
bd update <issue-id> --status in_progress
bd close <issue-id>
bd ready
```

Beads is not part of the submitted application. It is a lightweight engineering workflow record used while building the prototype.
