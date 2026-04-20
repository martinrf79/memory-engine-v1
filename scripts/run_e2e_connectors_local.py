from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8091"
REPORT_PATH = Path('/mnt/data/e2e_connectors_universal_report.json')


def wait_ready(timeout: float = 20.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(f"{BASE}/health", timeout=2.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("server_not_ready")


def check(name: str, ok: bool, details: dict, results: list[dict]) -> None:
    results.append({"name": name, "ok": bool(ok), "details": details})
    if not ok:
        raise AssertionError(f"{name} failed: {details}")


def main() -> int:
    env = os.environ.copy()
    env["USE_FAKE_FIRESTORE"] = "true"
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8091"], env=env)
    results: list[dict] = []
    try:
        wait_ready()
        client = httpx.Client(base_url=BASE, follow_redirects=True, timeout=10.0)

        # Register and project.
        r = client.post("/auth/register", json={"user_id": "martin", "password": "secret123", "project": "memoria-guia"})
        check("register", r.status_code == 200, {"status": r.status_code, "body": r.text}, results)
        r = client.post("/panel/projects", json={"project": "otro-proyecto"})
        check("create_project", r.status_code == 200, {"status": r.status_code}, results)

        # Panel save and retrieve.
        r = client.post("/panel/memories/manual", json={"project": "memoria-guia", "book_id": "general", "content": "Mi productor favorito es Alfa"})
        check("panel_save_manual", r.status_code == 200 and r.json().get("status") in {"stored", "ok"}, {"status": r.status_code, "body": r.text}, results)
        r = client.post("/panel/chat", json={"project": "memoria-guia", "book_id": "general", "message": "¿Cuál es mi productor favorito?"})
        ans = r.json().get("answer", "") if r.status_code == 200 else ""
        check("panel_chat_retrieves_manual", r.status_code == 200 and "Alfa".lower() in ans.lower(), {"status": r.status_code, "answer": ans}, results)
        r = client.post("/panel/chat", json={"project": "otro-proyecto", "book_id": "general", "message": "¿Cuál es mi productor favorito?"})
        ans2 = r.json().get("answer", "") if r.status_code == 200 else ""
        check("project_isolation", r.status_code == 200 and "alfa" not in ans2.lower(), {"status": r.status_code, "answer": ans2}, results)

        # Connect provider and inspect URLs.
        r = client.post("/connection/connect", json={"user_id": "martin", "provider": "chatgpt", "project": "memoria-guia"})
        body = r.json() if r.status_code == 200 else {}
        token = body.get("bridge_token")
        check("connect_provider", r.status_code == 200 and bool(token) and bool(body.get("mcp_sse_url")), {"status": r.status_code, "body": body}, results)

        # Remote MCP via SSE + JSON-RPC.
        r = httpx.get(body["mcp_sse_url"], timeout=10.0)
        check("mcp_sse_endpoint", r.status_code == 200 and "event: endpoint" in r.text, {"status": r.status_code, "text": r.text[:200]}, results)
        rpc_url = body["mcp_http_url"]
        r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init = r.json() if r.status_code == 200 else {}
        check("mcp_initialize", r.status_code == 200 and init.get("result", {}).get("protocolVersion"), {"status": r.status_code, "body": init}, results)
        r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = r.json().get("result", {}).get("tools", []) if r.status_code == 200 else []
        check("mcp_tools_list", r.status_code == 200 and any(t.get("name") == "search_memory" for t in tools), {"status": r.status_code, "tools": tools[:3]}, results)
        r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "save_note", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "content": "El país objetivo es España", "title": "Exportación"}}})
        save_note = r.json() if r.status_code == 200 else {}
        check("mcp_save_note", r.status_code == 200 and save_note.get("result", {}).get("structuredContent", {}).get("title") == "Exportación", {"status": r.status_code, "body": save_note}, results)
        r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_memory", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "query": "España"}}})
        search = r.json() if r.status_code == 200 else {}
        items = search.get("result", {}).get("structuredContent", {}).get("items", [])
        check("mcp_search_memory", r.status_code == 200 and any("españa" in item.get("preview", "").lower() for item in items), {"status": r.status_code, "items": items}, results)

        # Tool-calling URL.
        tool_manifest = httpx.get(body["tool_calling_manifest_url"], timeout=10.0)
        manifest = tool_manifest.json() if tool_manifest.status_code == 200 else {}
        check("tool_manifest", tool_manifest.status_code == 200 and manifest.get("function_calling_ready") is True, {"status": tool_manifest.status_code, "body": manifest}, results)
        r = httpx.post(body["tool_calling_call_url"], json={"user_id": "martin", "tool_name": "save_fact", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "producer", "entity_type": "producer", "entity_id": "alfa", "subject": "alfa", "relation": "country", "object": "Argentina"}}, timeout=10.0)
        tool_call = r.json() if r.status_code == 200 else {}
        check("tool_calling_save_fact", r.status_code == 200 and tool_call.get("ok") is True, {"status": r.status_code, "body": tool_call}, results)

        # Logout/login persistence.
        r = client.post("/auth/logout")
        check("logout", r.status_code == 200, {"status": r.status_code}, results)
        r = client.post("/auth/login", json={"user_id": "martin", "password": "secret123"})
        check("login_again", r.status_code == 200, {"status": r.status_code}, results)
        r = client.post("/panel/chat", json={"project": "memoria-guia", "book_id": "general", "message": "¿Cuál es mi productor favorito?"})
        ans3 = r.json().get("answer", "") if r.status_code == 200 else ""
        check("persistence_after_relogin", r.status_code == 200 and "alfa" in ans3.lower(), {"status": r.status_code, "answer": ans3}, results)

        report = {"total": len(results), "passed": sum(1 for x in results if x["ok"]), "failed": sum(1 for x in results if not x["ok"]), "results": results}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: report[k] for k in ["total", "passed", "failed"]}, ensure_ascii=False))
        print(f"report: {REPORT_PATH}")
        return 0
    finally:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
