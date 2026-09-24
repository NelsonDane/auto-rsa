# MCP Tool Installation
This project can also run as an [MCP](https://modelcontextprotocol.io) server, exposing `get_holdings`/`buy`/`sell` as tools for AI agents/assistants like [OpenCode](https://opencode.ai) or [Claude Desktop](https://claude.com/download). Unlike the Discord bot and CLI, most users will add this via `uvx` without cloning the repo or activating a virtual environment, so there's no natural project directory to hold a `.env` file. Pick whichever credential option below fits your setup, or mix both.

**Tip**: If you're having trouble setting up the MCP server, you can always paste this link into AI of choice and ask it to generate a working config for you.

## Generic Setup

**Option A: `.env` file + `cwd`**
Either:
- Create a `.env` file somewhere on your computer ([example](.env.example)) and fill in your brokerage credentials
- Set the same `environment` variables in your mcp server config

```jsonc
{
  "mcp": {
    "auto-rsa": {
      "type": "local",
      "command": ["uvx", "auto_rsa_bot", "mcp"],
      "cwd": "~/.config/auto-rsa", // directory containing your `.env` file
      "environment": {
        "SCHWAB_USERNAME": "{env:SCHWAB_USERNAME}",
        "SCHWAB_PASSWORD": "{env:SCHWAB_PASSWORD}"
      },
      "enabled": true
    }
  }
}
```

Both options can be combined: any variable already set in `environment` takes priority, and anything missing falls back to the `.env` file found via `cwd`.

By default, `buy`/`sell` tools run in dry-run mode unless the agent explicitly requests a real order, matching the CLI's default behavior.

## Client-specific setup

### OpenCode

Same config as [Generic Setup](#generic-setup) above — add it under `mcp` in `opencode.json`/`opencode.jsonc`.

### Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`), then fully restart the app:

```jsonc
{
  "mcpServers": {
    "auto-rsa": {
      "command": "uvx",
      "args": ["auto_rsa_bot", "mcp"],
      "cwd": "~/.config/auto-rsa",
      "env": {
        "SCHWAB_USERNAME": "...",
        "SCHWAB_PASSWORD": "..."
      }
    }
  }
}
```

### Claude Code

Add the same entry to `.mcp.json` (project scope, shared via version control) or `~/.claude.json` (user scope, private to you):

```jsonc
{
  "mcpServers": {
    "auto-rsa": {
      "command": "uvx",
      "args": ["auto_rsa_bot", "mcp"],
      "cwd": "~/.config/auto-rsa",
      "env": {
        "SCHWAB_USERNAME": "...",
        "SCHWAB_PASSWORD": "..."
      }
    }
  }
}
```
