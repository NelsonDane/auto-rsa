# MCP Tool Installation
This project can also run as an [MCP](https://modelcontextprotocol.io) server, exposing `get_holdings`/`buy`/`sell` as tools for AI agents/assistants like [OpenCode](https://opencode.ai) or [Claude Desktop](https://claude.com/download). Unlike the Discord bot and CLI, most users will add this via `uvx` without cloning the repo or activating a virtual environment, so there's no natural project directory to hold a `.env` file. Pick whichever credential option below fits your setup, or mix both.

**Tip**: If you're having trouble setting up the MCP server, you can always paste this link into AI of choice and ask it to generate a working config for you.

## Generic Setup

Credentials are supplied as environment variables to the MCP server process. Pick one option, or combine both:

**Option 1: `.env` file**
Create a `.env` file somewhere on your computer ([example](../.env.example)), fill in your brokerage credentials, then pass its **absolute** path to `uvx` with `--env-file` (`~` is not expanded):

```json
"args": ["--env-file", "/absolute/path/to/.env", "auto_rsa_bot@latest", "mcp"]
```

**Option 2: Environment variables in your MCP config**
Set the same variables directly in your MCP client's environment block (`env` or `environment` depending on the client).

**NOTE: If both are used, variables set in the MCP config take priority over those in the `.env` file.**

`@latest` makes uvx check for a new release each time the server starts, so restart your MCP client (or reconnect the server) to pick up a new version. To pin a version and update on your own schedule, replace it with a specific version (e.g. `auto_rsa_bot@2.3.0`).

By default, `buy`/`sell` tools run in dry-run mode unless the agent explicitly requests a real order, matching the CLI's default behavior.

## Client-specific setup

### OpenCode

Add under `mcp` in `opencode.json`/`opencode.jsonc`. OpenCode also supports `{env:VAR}` to reference variables from your shell:

```jsonc
{
  "mcp": {
    "auto-rsa": {
      "type": "local",
      "command": ["uvx", "--env-file", "/absolute/path/to/.env", "auto_rsa_bot@latest", "mcp"],
      "environment": {
        "SCHWAB_USERNAME": "{env:SCHWAB_USERNAME}",
        "SCHWAB_PASSWORD": "{env:SCHWAB_PASSWORD}"
      },
      "enabled": true
    }
  }
}
```

### Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`), then fully restart the app:

```jsonc
{
  "mcpServers": {
    "auto-rsa": {
      "command": "uvx",
      "args": ["--env-file", "/absolute/path/to/.env", "auto_rsa_bot@latest", "mcp"],
      "env": {
        "SCHWAB_USERNAME": "...",
        "SCHWAB_PASSWORD": "..."
      }
    }
  }
}
```

### Claude Code

Add the entry to `.mcp.json` (project scope, shared via version control) or under the top-level `mcpServers` in `~/.claude.json` (user scope, private to you):

```jsonc
{
  "mcpServers": {
    "auto-rsa": {
      "command": "uvx",
      "args": ["--env-file", "/absolute/path/to/.env", "auto_rsa_bot@latest", "mcp"],
      "env": {
        "SCHWAB_USERNAME": "...",
        "SCHWAB_PASSWORD": "..."
      }
    }
  }
}
```
