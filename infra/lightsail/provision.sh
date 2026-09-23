#!/usr/bin/env bash
# Provision KathaChepta on AWS Lightsail. NOT RUN YET — Phase 6, once AWS access is provided.
#
#   AWS_PROFILE=kathachepta ENV=staging ./infra/lightsail/provision.sh
#
# Creates: an Ubuntu instance, a static IP, firewall rules (22/80/443 only), a private bucket
# for media, and a CDN distribution in front of it. DNS records are printed for kathachepta.com.
set -euo pipefail

ENV="${ENV:-staging}"                       # staging | production
REGION="${REGION:-ap-south-1}"              # Mumbai: closest to Telugu-speaking listeners
ZONE="${ZONE:-${REGION}a}"
BUNDLE="${BUNDLE:-$([ "$ENV" = production ] && echo large_3_0 || echo medium_3_0)}"  # 8 GB / 4 GB
NAME="kathachepta-$ENV"
BUCKET="kathachepta-$ENV-media"
DOMAIN="${DOMAIN:-$([ "$ENV" = production ] && echo kathachepta.com || echo staging.kathachepta.com)}"

aws() { command aws --region "$REGION" "$@"; }

echo "== Instance $NAME ($BUNDLE) in $ZONE"
aws lightsail create-instances --instance-names "$NAME" --availability-zone "$ZONE" \
  --blueprint-id ubuntu_24_04 --bundle-id "$BUNDLE" \
  --user-data "$(cat "$(dirname "$0")/bootstrap.sh")" \
  --tags key=project,value=kathachepta key=env,value="$ENV"
aws lightsail enable-add-on --resource-name "$NAME" \
  --add-on-request addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=21:00}

echo "== Static IP"
aws lightsail allocate-static-ip --static-ip-name "$NAME-ip"
aws lightsail attach-static-ip --static-ip-name "$NAME-ip" --instance-name "$NAME"
IP=$(aws lightsail get-static-ip --static-ip-name "$NAME-ip" --query 'staticIp.ipAddress' --output text)

echo "== Firewall: SSH, HTTP, HTTPS only"
aws lightsail put-instance-public-ports --instance-name "$NAME" --port-infos \
  fromPort=22,toPort=22,protocol=tcp fromPort=80,toPort=80,protocol=tcp fromPort=443,toPort=443,protocol=tcp

echo "== Media bucket (private) and access key for the API"
aws lightsail create-bucket --bucket-name "$BUCKET" --bundle-id small_1_0
aws lightsail update-bucket --bucket-name "$BUCKET" --access-rules getObject=private,allowPublicOverrides=false
aws lightsail set-resource-access-for-bucket --bucket-name "$BUCKET" --resource-name "$NAME" --access read
aws lightsail create-bucket-access-key --bucket-name "$BUCKET" \
  --query 'accessKey.{id:accessKeyId,secret:secretAccessKey}' > "$NAME-bucket-key.json"
echo "Bucket key saved to $NAME-bucket-key.json — move it into the server's .env and delete the file."

cat <<EOF

== Next steps
1. DNS for $DOMAIN:   A  $DOMAIN      -> $IP
                      A  api.$DOMAIN  -> $IP   (production only)
   and for kadachepta.com: A -> $IP (Caddy redirects it to kathachepta.com).
2. SSH in (lightsail default key): ssh ubuntu@$IP
3. Fill /srv/kathachepta/.env (see .env.example; KC_ENVIRONMENT=production, KC_COOKIE_SECURE=true,
   KC_STAFF_MFA_REQUIRED=true, KC_STORAGE_BACKEND=s3 + bucket keys).
4. cd /srv/kathachepta && docker compose -f docker-compose.yml -f infra/lightsail/docker-compose.prod.yml up -d --build
5. Migrate data from the desktop: pg_dump there, pg_restore here; sync data/media to the bucket.
EOF
