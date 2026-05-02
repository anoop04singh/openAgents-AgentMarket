#!/usr/bin/env node

const ports = {
  axl: [9002, 9012, 9022],
  mcp: [9003, 9013, 9023],
};

async function httpJson(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(url, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const text = await res.text();
    let data = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {}
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(timer);
  }
}

function section(name) {
  console.log(`\n=== ${name} ===`);
}

function pickTool(names, preferred, fallback) {
  if (names.includes(preferred)) return preferred;
  if (names.includes(fallback)) return fallback;
  return preferred;
}

async function main() {
  section("1. AXL Node Topology");
  for (const port of ports.axl) {
    try {
      const topology = await httpJson(`http://127.0.0.1:${port}/topology`);
      if (!topology.ok) {
        console.log(`[warn] AXL ${port}: topology status=${topology.status}`);
        continue;
      }
      const peers = Array.isArray(topology.data?.peers) ? topology.data.peers.length : "unknown";
      const own = topology.data?.our_public_key || topology.data?.public_key || "unknown";
      console.log(`[ok] AXL ${port}: peers=${peers} publicKey=${String(own).slice(0, 24)}...`);
    } catch (error) {
      console.log(`[fail] AXL ${port}: ${error.message}`);
    }
  }

  section("2. MCP Tool Discovery");
  for (const port of ports.mcp) {
    try {
      const tools = await httpJson(`http://127.0.0.1:${port}/mcp`, {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/list",
        params: {},
      });
      if (!tools.ok) {
        console.log(`[warn] MCP ${port}: tools/list status=${tools.status}`);
        continue;
      }
      const names = tools.data?.result?.tools?.map((tool) => tool.name) || [];
      console.log(`[ok] MCP ${port}: ${names.join(", ")}`);
    } catch (error) {
      console.log(`[fail] MCP ${port}: ${error.message}`);
    }
  }

  section("3. MCP Tool Calls");
  for (const port of ports.mcp) {
    let names = [];
    try {
      const tools = await httpJson(`http://127.0.0.1:${port}/mcp`, {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/list",
        params: {},
      });
      names = tools.data?.result?.tools?.map((tool) => tool.name) || [];
    } catch {}
    const cardTool = pickTool(names, "get_agent_card", "get_card");
    const voteTool = pickTool(names, "get_vote_intention", "get_vote");
    const calls = [
      [cardTool, {}],
      ["get_probability", { market_address: "0x0000000000000000000000000000000000000000" }],
      [voteTool, { market_address: "0x0000000000000000000000000000000000000000" }],
    ];
    if (names.includes("list_positions")) {
      calls.push(["list_positions", {}]);
    }
    for (const [name, args] of calls) {
      try {
        const result = await httpJson(`http://127.0.0.1:${port}/mcp`, {
          jsonrpc: "2.0",
          id: Date.now(),
          method: "tools/call",
          params: { name, arguments: args },
        });
        if (!result.ok) {
          console.log(`[warn] MCP ${port}.${name}: status=${result.status}`);
          continue;
        }
        const text = result.data?.result?.content?.[0]?.text || "{}";
        console.log(`[ok] MCP ${port}.${name}: ${text.slice(0, 180)}`);
      } catch (error) {
        console.log(`[fail] MCP ${port}.${name}: ${error.message}`);
      }
    }
  }

  section("4. Communication Summary");
  console.log("AXL topology proves separate node connectivity.");
  console.log("MCP tools prove structured cross-agent service compatibility.");
  console.log("Use agent logs to watch live AXL broadcasts: tail -f logs/agent-a.log logs/agent-b.log logs/agent-c.log");
}

main().catch((error) => {
  console.error(`[fail] ${error.stack || error.message}`);
  process.exit(1);
});
