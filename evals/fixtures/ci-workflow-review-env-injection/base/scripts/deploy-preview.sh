#!/bin/sh
# Publishes ./public as the preview site for pull request $PR_NUMBER.
set -eu
case "$PR_NUMBER" in
  ''|*[!0-9]*) echo "bad PR number" >&2; exit 1 ;;
esac
echo "Deploying preview for ${PR_BRANCH:-unknown branch}"
tar -czf site.tgz public
curl --fail -sS -H "Authorization: Bearer $PREVIEW_DEPLOY_TOKEN" \
  --data-binary @site.tgz "https://previews.example.com/api/sites/pr-$PR_NUMBER"
