# CLI Coding Agents

Five coding agents are installed and ready to use. Each has its own
strengths — pick the right tool for the job.

## Agent overview

| Agent | Command | Vendor | Best for |
|-------|---------|--------|----------|
| **Codewhale** | `codewhale` | CodeWhale | Multi-file refactors, repo-scale tasks, shell access |
| **Codex** | `codex` | OpenAI | Fast iteration, CLI-native, sandboxed execution |
| **Claude Code** | `claude` | Anthropic | Large codebases, long sessions, design work |
| **OpenCode** | `opencode` | OpenCode | Open-source agent, terminal-native, configurable |
| **Copilot CLI** | `copilot` | GitHub | Shell command generation, git commit messages, PRs |

## Setting up API keys

Most agents need API keys set as environment variables. Add these to your
shell profile (outside this repo — never commit secrets).

### Codewhale
```bash
export CODEWHALE_API_KEY="sk-..."
```
[Sign up →](https://codewhale.ai)

### Codex (OpenAI)
```bash
export OPENAI_API_KEY="sk-..."
```
[Sign up →](https://platform.openai.com/api-keys)

### Claude Code
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
First run walks you through OAuth or API key setup.
[Sign up →](https://console.anthropic.com)

### OpenCode
```bash
export OPENAI_API_KEY="sk-..."       # or
export ANTHROPIC_API_KEY="sk-ant-..." # or
export OPENROUTER_API_KEY="sk-or-..."
```
Can use multiple providers. Run `opencode` to configure.

### GitHub Copilot CLI
```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="ghp_..."
gh auth login
```
The Copilot CLI extension also works with OpenRouter:
```bash
export COPILOT_PROVIDER_BASE_URL="https://openrouter.ai/api/v1"
export COPILOT_PROVIDER_API_KEY="sk-or-..."
export COPILOT_PROVIDER_MODEL_ID="deepseek-v4-pro"
export COPILOT_PROVIDER_WIRE_MODEL="deepseek/deepseek-v4-pro"
```

## Quick reference

```bash
# Shell completion / commands
copilot suggest "find large files"       # Generate a shell command
copilot git-explain                      # Explain the last git command

# Code generation (any agent)
codewhale "add input validation to login form"
codex "refactor this function to async"
claude "review this PR for security issues"
opencode "generate unit tests for this module"

# Tmux integration
# The 'dev' alias launches opencode in pre-configured tmux windows
dev
```

## Tmux dev session

Running `dev` opens a tmux session with:
- Window 1: Opencode in `$HOME`
- Window 2: Opencode in `~/Documents/jimber/jimberfw`
- Window 3: Opencode in `~/Documents/jimber/jimberfw_signalserver`
- Window 4: Regular CLI

Edit `~/.config/tmux/dev-session` to customize.

## Energy / cost

| Agent | Cost model | Offline? |
|-------|-----------|----------|
| Codewhale | Subscription / credits | No |
| Codex | OpenAI API (pay-per-token) | No |
| Claude Code | Anthropic API (pay-per-token) | No |
| OpenCode | Your API keys (any provider) | No |
| Copilot CLI | Copilot subscription | No |

All agents require internet access.

## Switching providers

OpenCode and Copilot CLI can route through OpenRouter for access to
multiple models without separate API keys:

```
OpenRouter → deepseek-v4-pro (cheap, fast)
           → claude-sonnet-4-20250514 (balanced)
           → gpt-4o (strongest)
```

Configure in `~/.config/opencode/config.toml` or via the Copilot env vars above.
