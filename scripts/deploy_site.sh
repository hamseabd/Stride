#!/usr/bin/env bash
set -euo pipefail

BUCKET="stride-productivity-site"
SOURCE="scrumbot-app/site/"

echo "Syncing site to s3://${BUCKET}/ ..."

# Sync HTML files
aws s3 sync "${SOURCE}" "s3://${BUCKET}/" \
  --exclude "*" \
  --include "*.html" \
  --content-type "text/html" \
  --cache-control "max-age=3600"

# Sync CSS files
aws s3 sync "${SOURCE}" "s3://${BUCKET}/" \
  --exclude "*" \
  --include "*.css" \
  --content-type "text/css" \
  --cache-control "max-age=3600"

# Sync XML + TXT files
aws s3 sync "${SOURCE}" "s3://${BUCKET}/" \
  --exclude "*.html" \
  --exclude "*.css" \
  --cache-control "max-age=3600" \
  --delete

ENDPOINT="http://${BUCKET}.s3-website-us-east-1.amazonaws.com"

echo ""
echo "Deploy complete. Site available at:"
echo "  Home:             ${ENDPOINT}/"
echo "  Privacy Policy:   ${ENDPOINT}/privacy-policy.html"
echo "  Terms of Service: ${ENDPOINT}/terms-of-service.html"
