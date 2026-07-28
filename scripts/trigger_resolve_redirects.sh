#!/usr/bin/env bash
# Trigger Resolve Redirect URLs Workflow
# Owner: AKTHACKER24
# Repo: scraper
# Workflow: .github/workflows/resolve_redirects.yml

OWNER="${1:-AKTHACKER24}"
REPO="${2:-scraper}"
TOTAL_CHUNKS="${3:-40}"
CHUNK_SIZE="${4:-500}"
MAX_WORKERS="${5:-15}"
LIMIT="${6:-}"

echo "=========================================================="
echo " Triggering Workflow: resolve_redirects.yml"
echo " Target Repository:   ${OWNER}/${REPO}"
echo " Total Matrix Chunks: ${TOTAL_CHUNKS}"
echo " Chunk Size:          ${CHUNK_SIZE}"
echo " Max HTTP Workers:    ${MAX_WORKERS}"
if [ -n "$LIMIT" ]; then
  echo " Record Limit:        ${LIMIT}"
fi
echo "=========================================================="

if command -v gh &> /dev/null; then
  echo "Using GitHub CLI (gh)..."
  GH_CMD=("gh" "workflow" "run" "resolve_redirects.yml" "--repo" "${OWNER}/${REPO}" "-f" "total_chunks=${TOTAL_CHUNKS}" "-f" "chunk_size=${CHUNK_SIZE}" "-f" "max_workers=${MAX_WORKERS}")
  if [ -n "$LIMIT" ]; then
    GH_CMD+=("-f" "limit=${LIMIT}")
  fi
  "${GH_CMD[@]}"
  echo "✓ Triggered via gh CLI!"
else
  TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"
  if [ -z "$TOKEN" ]; then
    echo "Error: Neither gh CLI nor GITHUB_TOKEN / GH_TOKEN environment variable was found."
    exit 1
  fi
  echo "Using cURL API call..."
  curl -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/resolve_redirects.yml/dispatches" \
    -d "{\"ref\":\"main\",\"inputs\":{\"total_chunks\":\"${TOTAL_CHUNKS}\",\"chunk_size\":\"${CHUNK_SIZE}\",\"max_workers\":\"${MAX_WORKERS}\",\"limit\":\"${LIMIT}\"}}"
  echo ""
  echo "✓ Triggered via GitHub REST API!"
fi
