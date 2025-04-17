# MCP Gateway

![Hugging Face Token Masking Example](docs/MCP_Flow.png)

MCP Gateway is an advanced intermediary solution for Model Context Protocol (MCP) servers that centralizes and enhances your AI infrastructure.

MCP Gateway acts as an intermediary between LLMs and other MCP servers. It:

1. Reads server configurations from a `mcp.json` file located in your root directory.
2. Manages the lifecycle of configured MCP servers.
3. Intercepts requests and responses to sanitize sensitive information.
4. Provides a unified interface for discovering and interacting with all proxied MCPs.

## Installation
Install the mcp-gateway package:
```bash
pip install mcp-gateway
```

> `--mcp-json-path` - must lead to your [mcp.json](https://docs.cursor.com/context/model-context-protocol#configuration-locations) or [claude_desktop_config.json](https://modelcontextprotocol.io/quickstart/server#testing-your-server-with-claude-for-desktop)

> `--enable-guardrails` - you can use this to activate multiple guardrail plugins

Cursor example:
```json
{
  "mcpServers": {
      "mcp-gateway": {
          "command": "mcp-gateway",
          "args": [
              "--mcp-json-path",
              "~/.cursor/mcp.json",
              "--enable-guardrails",
              "basic"
          ],
          "servers": {
              "filesystem": {
                  "command": "npx",
                  "args": [
                      "-y",
                      "@modelcontextprotocol/server-filesystem",
                      "."
                  ]
              }
          }
      }
  }
}
```

This example gives you the basic and presidio guardrails for token and PII masking for filesystem MCP.
You can add more MCPs that will be under the Gateway by putting the MCP server configuration under the "servers" key.

## Quickstart

### Masking Sensitive Information

MCP Gateway will automatically mask the sensitive token in the response, preventing exposure of credentials while still providing the needed functionality.

1. Create a file with sensitive information:
   ```bash
   echo 'HF_TOKEN = "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"' > tokens.txt
   ```

2. When an agent requests to read this file through MCP Gateway:   
    - Recommend to test with sonnet 3.7
   ```
   Use your mcp-gateway tools to read the ${pwd}/tokens.txt and return the HF_TOKEN
   ```
   
**Output:** 

![Hugging Face Token Masking Example](docs/hf_example.png)

## Usage

Start the MCP Gateway server with python_env config on this repository root:

```bash
mcp-gateway --enable-guardrails basic --enable-guardrails presidio
```

You can also debug the server using:
```bash
LOGLEVEL=DEBUG mcp-gateway --mcp-json-path ~/.cursor/mcp.json --enable-guardrails basic --enable-guardrails presidio
```

## Tools

Here are the tools the MCP is using to create a proxy to the other MCP servers

- **`get_metadata`** - Provides information about all available proxied MCPs to help LLMs choose appropriate tools and resources
- **`run_tool`** - Executes capabilities from any proxied MCP after sanitizing the request and response

# Plugins

## Contribute
For more details on how the plugin system works, how to create your own plugins, or how to contribute, please see the [Plugin System Documentation](./mcp_gateway/plugins/README.md).

## Guardrails
MCP Gateway supports various plugins to enhance security and functionality. Here's a summary of the built-in guardrail plugins:


| Name | PII Masking                                                              | Token/Secret Masking                                                                 | Custom Policy | Prompt Injection | Harmful Content |
| :---------- | :----------------------------------------------------------------------- | :----------------------------------------------------------------------------------- | :-----------: | :------------------: | :-------------: |
| `basic`     | ❌                                                                       | ✅                                                         | ❌            | ❌                   | ❌              |
| `presidio`  | ✅  | ❌                                                                                   | ❌            | ❌                   | ❌              |
| `lasso`     | ✅                                                                       | ✅                                                                                   | ✅            | ✅                   | ✅              |

**Note:** To use the `presidio` plugin, you need to install it separately: `pip install mcp-gateway[presidio]`.


### Basic 
```bash
mcp-gateway --enable-guardrails basic
```
Masking basic secerts
- azure client secret
- github tokens
- github oauth
- gcp api key
- aws access token
- jwt token
- gitlab session cookie
- huggingface access token
- microsoft teams webhook
- slack app token

### Presidio 
```bash
mcp-gateway --enable-guardrails presidio
```
[Presidio](https://microsoft.github.io/presidio/) is identification and anonymization package
- Credit Card
- IP
- Email
- Phone
- SSN
- [Etc](https://microsoft.github.io/presidio/supported_entities/)

### Lasso 
```bash
mcp-gateway --enable-guardrails lasso
```
#### Prerequisites
- **Obtain a Lasso API key** by signing up at [Lasso Security](https://www.lasso.security/).

To use Lasso Security's advanced AI safety guardrails, update your `mcp.json` configuration as follows:

1. Add the `LASSO_API_KEY=<YOUR-API-KEY>` to your environment variable or in the "env" section.
2. Insert other MCP servers configuration under key `servers`

Example:

```json
{
  "mcpServers": {
      "mcp-gateway": {
          "command": "mcp-gateway",
          "args": [
              "--mcp-json-path",
              "~/.cursor/mcp.json",
              "--enable-guardrails",
              "lasso"
          ],
          "env": {
              "LASSO_API_KEY": "<lasso_token>"
          },
          "servers": {
              "filesystem": {
                  "command": "npx",
                  "args": [
                      "-y",
                      "@modelcontextprotocol/server-filesystem",
                      "."
                  ]
              }
          }
      }
  }
}
```


#### Features

🔍 Full visibility into MCP interactions with an Always-on monitoring.

🛡️ Mitigate GenAI-specific threats like prompt injection and sensitive data leakage in real-time with built-in protection that prioritizes security from deployment.

✨ Use flexible, natural language to craft security policies tailored to your business's unique needs.

⚡ Fast and easy installation for any deployment style. Monitor data flow to and from MCP in minutes with an intuitive, user-friendly dashboard.


The Lasso guardrail checks content through Lasso's API for security violations before processing requests and responses.

Read more on our website 👉 [Lasso Security](https://www.lasso.security/).

## How It Works
Your agent interacts directly with our MCP Gateway, which functions as a central router and management system. Each underlying MCP is individually wrapped and managed.

Key Features

**Agnostic Guardrails**
* Applies configurable security filters to both requests and responses.
* Prevents sensitive data exposure before information reaches your agent.
* Works consistently across all connected MCPs regardless of their native capabilities.

**Unified Visibility**
* Provides comprehensive dashboard for all your MCPs in a single interface.
* Includes intelligent risk assessment with MCP risk scoring.
* Delivers real-time status monitoring and performance metrics.

**Advanced Tracking**
* Maintains detailed logs of all requests and responses for each guardrail.
* Offers cost evaluation tools for MCPs requiring paid tokens.
* Provides usage analytics and pattern identification for optimization.
* Sanitizes sensitive information before forwarding requests to other MCPs.

## Tracing

### Xetrack
[xetrack](https://github.com/xdssio/xetrack) is a lightweight package to track ml experiments, benchmarks, and monitor stractured data.

We can use it to debug and monitor **tool calls** with logs ([loguru](https://github.com/Delgan/loguru)) or [duckdb](https://duckdb.org) and [sqlite](https://sqlite.org).   .

```bash
mcp-gateway --enable-tracing xetrack

```
#### Prerequisites
`pip install xetrack`

#### Params
* `XETRACK_DB_PATH` - The sqlite db location. 
    * All logs register in the *events* table.
    * If fancy objects return from the MCPs response, read about xetrack [assets](https://github.com/xdssio/xetrack?tab=readme-ov-file#track-assets-oriented-for-ml-models) to retrive it. 
* `XETRACK_LOGS_PATH` - The logs location
* `FLATTEN_ARGUMENTS` - Flatten the arguments, default `true`
* `FLATTEN_RESPONSE` - Flatten the response, default `true`
* It is recommend to to gitignore the logs location
* It is recommended to use [DVC](http://dvc.org) to manage the db file

#### Quickstart 
```json
{
    "mcpServers": {
        "mcp-gateway": {
            "command": "mcp-gateway",
            "args": [
                "--mcp-json-path",
                "~/development/xdss/mcp-gateway/.cursor/mcp.json",
                "--enable-tracing",
                "xetrack"
            ],
            "env": {
                "XETRACK_DB_PATH": "tracing.db",
                "XETRACK_LOGS_PATH": "logs/",                
            },
            "servers": {
                "filesystem": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        "."
                    ]
                }
            }
        }
    }
}
```

Let's say you use the  filesystem *list_directory* tool on path *"."*, you can find the call parameters under `logs/<date>.log`.

You can expolre using [xetrack cli](https://github.com/xdssio/xetrack?tab=readme-ov-file#cli) to query the db:

```bash
$ xt tail tracing.db --json --n=1
[
    {
        "timestamp": "2025-04-17 17:12:48.233126",
        "track_id": "mottled-stingray-0411",
        "meta": "f3be31e09667745f",
        "paths": null,
        "call_id": "deab617e-0a45-4950-9de9-3fb549810cf2",
        "capability_name": "list_directory",
        "content_type": "text",
        "content_annotations": "f3be31e09667745f",
        "response_type": "CallToolResult",
        "server_name": "filesystem",
        "capability_type": "tool",
        "isError": 0,
        "content_text": "[DIR] .cursor\n[DIR] .git\n[FILE] .gitignore\n[DIR] .pytest_cache\n[DIR] .venv\n[FILE] LICENSE\n[FILE] MANIFEST.in\n[FILE] README.md\n[DIR] docs\n[DIR] logs\n[DIR] mcp_gateway\n[FILE] pyproject.toml\n[FILE] requirements.txt\n[DIR] tests\n[DIR] tmp",
        "path": ".",
        "prompt": null
    }
]
```
With python
```python
from xetrack import Reader

df = Reader("tracing.db").to_df()
```


With duckdb cli and ui 
```bash
$ duckdb --ui
D INSTALL sqlite; LOAD sqlite; ATTACH 'tracing.db' (TYPE sqlite);
D SELECT server_name,capability_name,path,content_text FROM db.events LIMIT 1;

┌─────────────┬─────────────────┬─────────┬────────────────────────────────────┐
│ server_name │ capability_name │  path   │            content_text            │
│   varchar   │     varchar     │ varchar │              varchar               │
├─────────────┼─────────────────┼─────────┼────────────────────────────────────┤
│ filesystem  │ list_directory  │ .       │ [DIR] .cursor\n[DIR] .git\n[FILE…  │
└─────────────┴─────────────────┴─────────┴────────────────────────────────────┘
```

Of course you can use another MCP server to query the sqlite database 😊



## License

MIT

