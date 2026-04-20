from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8092"
REPORT_PATH = Path('/mnt/data/e2e_second_round_report.json')
PROVIDERS = ["chatgpt", "claude", "gemini", "deepseek"]


def wait_ready(timeout: float = 25.0) -> None:
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
    env["ENABLE_ADMIN_PANEL"] = "true"
    env["ADMIN_TOKEN"] = "super-admin"
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8092"], env=env)
    results: list[dict] = []
    try:
        wait_ready()
        client = httpx.Client(base_url=BASE, follow_redirects=True, timeout=10.0)
        admin_headers = {"x-admin-token": "super-admin"}

        r = client.post("/auth/register", json={"user_id": "martin", "password": "secret123", "project": "memoria-guia"})
        check("register", r.status_code == 200, {"status": r.status_code, "body": r.text}, results)
        r = client.post("/panel/memories/manual", json={"project": "memoria-guia", "book_id": "general", "content": "Mi productor favorito es Alfa"})
        check("seed_manual_note", r.status_code == 200, {"status": r.status_code, "body": r.text}, results)

        for provider in PROVIDERS:
            r = client.post("/connection/connect", json={"user_id": "martin", "provider": provider, "project": "memoria-guia"})
            body = r.json() if r.status_code == 200 else {}
            token = body.get("bridge_token")
            check(f"connect_{provider}", r.status_code == 200 and bool(token), {"status": r.status_code, "body": body}, results)
            r = client.get(f"/bridge/{provider}/manifest?token={token}")
            manifest = r.json() if r.status_code == 200 else {}
            check(f"bridge_manifest_{provider}", r.status_code == 200 and manifest.get("provider") == provider, {"status": r.status_code, "body": manifest}, results)
            r = client.post(f"/bridge/{provider}/tool-call?token={token}", json={"user_id": "martin", "tool_name": "search_memory", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "query": "productor favorito"}})
            bridge_body = r.json() if r.status_code == 200 else {}
            bridge_items = bridge_body.get("result", {}).get("items", []) if isinstance(bridge_body, dict) else []
            check(f"bridge_search_{provider}", r.status_code == 200 and bridge_body.get("ok") is True and bool(bridge_items), {"status": r.status_code, "body": bridge_body}, results)
            r = client.get(f"/tool-calling/{provider}/manifest?token={token}")
            tool_manifest = r.json() if r.status_code == 200 else {}
            check(f"tool_manifest_{provider}", r.status_code == 200 and tool_manifest.get("function_calling_ready") is True, {"status": r.status_code, "body": tool_manifest}, results)
            r = client.post(f"/tool-calling/{provider}/call?token={token}", json={"user_id": "martin", "tool_name": "search_memory", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "query": "productor favorito"}})
            tool_body = r.json() if r.status_code == 200 else {}
            tool_items = tool_body.get("result", {}).get("items", []) if isinstance(tool_body, dict) else []
            check(f"tool_search_{provider}", r.status_code == 200 and tool_body.get("ok") is True and bool(tool_items), {"status": r.status_code, "body": tool_body}, results)
            if provider in {"chatgpt", "claude"}:
                r = httpx.post(body["mcp_http_url"], json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, timeout=10.0)
                init = r.json() if r.status_code == 200 else {}
                check(f"mcp_initialize_{provider}", r.status_code == 200 and bool(init.get("result", {}).get("protocolVersion")), {"status": r.status_code, "body": init}, results)
                r = httpx.post(body["mcp_http_url"], json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_memory", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "query": "productor favorito"}}}, timeout=10.0)
                rpc = r.json() if r.status_code == 200 else {}
                rpc_items = rpc.get("result", {}).get("structuredContent", {}).get("items", []) if isinstance(rpc, dict) else []
                check(f"mcp_search_{provider}", r.status_code == 200 and bool(rpc_items), {"status": r.status_code, "body": rpc}, results)

        r = client.post("/tool-calling/generic/call", json={"user_id": "martin", "tool_name": "search_memory", "arguments": {"tenant_id": "martin", "project_id": "memoria-guia", "book_id": "general", "query": "productor favorito"}})
        generic = r.json() if r.status_code == 200 else {}
        check("tool_search_generic", r.status_code == 200 and generic.get("ok") is True and bool(generic.get("result", {}).get("items")), {"status": r.status_code, "body": generic}, results)

        r = client.get("/admin/connectors/self-check?user_id=martin", headers=admin_headers)
        admin_self = r.json() if r.status_code == 200 else {}
        check("admin_connectors_self_check", r.status_code == 200 and admin_self.get("status") == "ok" and len(admin_self.get("checks", [])) >= 5, {"status": r.status_code, "body": admin_self}, results)
        r = client.get("/admin/maintenance/verify", headers=admin_headers)
        maintenance = r.json() if r.status_code == 200 else {}
        check("admin_maintenance_verify", r.status_code == 200 and maintenance.get("status") in {"ok", "warning"}, {"status": r.status_code, "body": maintenance}, results)

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
