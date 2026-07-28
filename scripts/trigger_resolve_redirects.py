#!/usr/bin/env python3
"""
Trigger GitHub Actions Workflow: resolve_redirects.yml
Repository: AKTHACKER24/scraper
Workflow: .github/workflows/resolve_redirects.yml
"""

import os
import sys
import argparse
import json
import requests


def trigger_workflow(owner, repo, workflow, token, total_chunks="40", chunk_size="500", max_workers="15", limit=""):
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    inputs = {
        "total_chunks": str(total_chunks),
        "chunk_size": str(chunk_size),
        "max_workers": str(max_workers),
    }
    if limit:
        inputs["limit"] = str(limit)

    payload = {
        "ref": "main",
        "inputs": inputs
    }

    print(f"Triggering workflow '{workflow}' on '{owner}/{repo}'...")
    print(f"Inputs: {json.dumps(inputs, indent=2)}")

    res = requests.post(url, headers=headers, json=payload)
    if res.status_code == 204:
        print("✓ Workflow dispatch triggered successfully!")
        return True
    else:
        print(f"FAILED to trigger workflow ({res.status_code}): {res.text}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Trigger Resolve Redirect URLs Workflow on GitHub Actions")
    parser.add_argument("--owner", default=os.getenv("GITHUB_OWNER", "AKTHACKER24"), help="GitHub Repository Owner (default: AKTHACKER24)")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPO", "scraper"), help="GitHub Repository Name (default: scraper)")
    parser.add_argument("--workflow", default="resolve_redirects.yml", help="Workflow filename (default: resolve_redirects.yml)")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"), help="GitHub Personal Access Token (PAT)")
    parser.add_argument("--total-chunks", default="40", help="Number of parallel matrix worker jobs (default: 40)")
    parser.add_argument("--chunk-size", default="500", help="Records per chunk within each worker (default: 500)")
    parser.add_argument("--max-workers", default="15", help="Concurrent HTTP worker threads per job (default: 15)")
    parser.add_argument("--limit", default="", help="Optional limit per job")

    args = parser.parse_args()

    token = args.token
    if not token:
        print("Error: GitHub Token is required. Pass --token or set GITHUB_TOKEN / GH_TOKEN env var.", file=sys.stderr)
        sys.exit(1)

    success = trigger_workflow(
        owner=args.owner,
        repo=args.repo,
        workflow=args.workflow,
        token=token,
        total_chunks=args.total_chunks,
        chunk_size=args.chunk_size,
        max_workers=args.max_workers,
        limit=args.limit
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
