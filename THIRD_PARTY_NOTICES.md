# Third-party notices

## data-go-mcp-servers reference

The local Data.go.kr MCP implementation was rewritten under
`connectors/mcp_platform/servers/`. The repository does not execute or ship the
upstream source tree; the upstream project was used as a functional/API
reference during the rewrite.

- Repository: https://github.com/Koomook/data-go-mcp-servers
- Reference snapshot: `dd27f99490400b31fa14f96045a138fa217580a4`
- Upstream license: Apache License 2.0

The local project license is in the repository root `LICENSE`. No upstream
source tree is included in the runtime or distribution.

The local implementation has its own maintenance history and changes. API
terms and the license of data returned by each public service remain separate
from the software license.

The upstream project is not an official project of the Korean government or
data.go.kr.

## Go MCP SDK and architecture reference

The Go starter depends on `github.com/modelcontextprotocol/go-sdk` v1.7.0 for
MCP protocol support. Its license is available in the
[official SDK repository](https://github.com/modelcontextprotocol/go-sdk).

The `cmd/` and internal package layout was informed by
[GitHub's MCP server](https://github.com/github/github-mcp-server). No source
code from that server is included in this repository.
