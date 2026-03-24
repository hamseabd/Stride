#!/usr/bin/env bash
set -euo pipefail

BUCKET="stride-productivity-site"
SOURCE="scrumbot-app/site/"

echo "Syncing site to s3://${BUCKET}/ ..."

aws s3 sync "${SOURCE}" "s3://${BUCKET}/" \
  --content-type "text/html" \
  --cache-control "max-age=3600" \
  --delete

ENDPOINT="http://${BUCKET}.s3-website-us-east-1.amazonaws.com"

echo ""
echo "Deploy complete. Site available at:"
echo "  Home:             ${ENDPOINT}/"
echo "  Privacy Policy:   ${ENDPOINT}/privacy-policy.html"
echo "  Terms of Service: ${ENDPOINT}/terms-of-service.html"
