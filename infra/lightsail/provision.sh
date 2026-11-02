#!/usr/bin/env bash
# Create the KathaChepta server on AWS Lightsail. Runbook: docs/lightsail-pilot.md (step 1).
# Runs anywhere the AWS CLI is signed in; AWS CloudShell (in the console) needs no setup:
#
#   git clone https://github.com/juluriaj/kadachepta.git && cd kadachepta
#   ALERT_EMAIL=you@example.com bash infra/lightsail/provision.sh
#
# Creates: an Ubuntu 24.04 instance that installs Docker and clones this repository on first boot, daily
# automatic snapshots, a static IP, firewall rules (SSH, HTTP, HTTPS only) and, with ALERT_EMAIL, email alarms.
# Media stays on the instance disk for the pilot (a bucket and CDN come later; see the runbook).
set -euo pipefail

ENV="${ENV:-production}"
REGION="${REGION:-ap-south-1}"              # Mumbai: closest to Telugu-speaking listeners
ZONE="${ZONE:-${REGION}a}"
BUNDLE="${BUNDLE:-micro_3_1}"               # $7/month: 1 GB RAM, 2 vCPU, 40 GB SSD. Later: medium_3_1 ($24, 4 GB)
                                            # from a snapshot (runbook, "Moving to a bigger plan")
NAME="kathachepta-$ENV"
SSH_CIDR="${SSH_CIDR:-0.0.0.0/0}"           # e.g. your home IP/32 to allow SSH only from there
KEY_PAIR="${KEY_PAIR:-}"                    # a key imported into Lightsail; empty = the region's default key
ALERT_EMAIL="${ALERT_EMAIL:-}"

aws() { command aws --region "$REGION" --output text "$@" | tr -d '\r'; }  # \r: the Windows CLI

echo "== Checking the AWS sign-in and bundle"
aws sts get-caller-identity --query Account >/dev/null \
  || { echo "!! The AWS CLI isn't signed in. Use AWS CloudShell, or run: aws configure" >&2; exit 1; }
if [ -z "$(aws lightsail get-bundles --query "bundles[?bundleId=='$BUNDLE'].bundleId")" ]; then
  echo "!! Bundle $BUNDLE doesn't exist in $REGION. Available Linux bundles:" >&2
  aws lightsail get-bundles --query "bundles[?contains(supportedPlatforms, 'LINUX_UNIX')].[bundleId,ramSizeInGb,diskSizeInGb,price]" >&2
  exit 1
fi
if aws lightsail get-instance --instance-name "$NAME" --query instance.name >/dev/null 2>&1; then
  echo "!! $NAME already exists in $REGION. Delete it in the console first, or use ENV=<other name>." >&2
  exit 1
fi

# Lightsail puts its own "#!/bin/sh" lines in front of the user data, so bootstrap.sh's shebang is ignored
# and sh stops at "set -o pipefail". Save the script on the server and run it with bash instead.
USER_DATA="cat > /root/kathachepta-bootstrap.sh <<'KC_BOOTSTRAP'
$(cat "$(dirname "$0")/bootstrap.sh")
KC_BOOTSTRAP
bash /root/kathachepta-bootstrap.sh"

echo "== Instance $NAME ($BUNDLE) in $ZONE"
aws lightsail create-instances --instance-names "$NAME" --availability-zone "$ZONE" \
  --blueprint-id ubuntu_24_04 --bundle-id "$BUNDLE" ${KEY_PAIR:+--key-pair-name "$KEY_PAIR"} \
  --user-data "$USER_DATA" \
  --tags key=project,value=kathachepta key=env,value="$ENV" >/dev/null
for _ in $(seq 60); do
  [ "$(aws lightsail get-instance-state --instance-name "$NAME" --query state.name)" = running ] && break
  sleep 5
done
aws lightsail enable-add-on --resource-name "$NAME" \
  --add-on-request 'addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=21:00}' >/dev/null  # 02:30 IST

echo "== Static IP"
aws lightsail allocate-static-ip --static-ip-name "$NAME-ip" >/dev/null
aws lightsail attach-static-ip --static-ip-name "$NAME-ip" --instance-name "$NAME" >/dev/null
IP=$(aws lightsail get-static-ip --static-ip-name "$NAME-ip" --query 'staticIp.ipAddress')

echo "== Firewall: SSH, HTTP, HTTPS (and HTTP/3) only"
aws lightsail put-instance-public-ports --instance-name "$NAME" --port-infos \
  "fromPort=22,toPort=22,protocol=tcp,cidrs=$SSH_CIDR" fromPort=80,toPort=80,protocol=tcp \
  fromPort=443,toPort=443,protocol=tcp fromPort=443,toPort=443,protocol=udp >/dev/null

if [ -n "$ALERT_EMAIL" ]; then
  echo "== Alarms to $ALERT_EMAIL (confirm the email AWS sends you)"
  aws lightsail create-contact-method --protocol Email --contact-endpoint "$ALERT_EMAIL" >/dev/null \
    || echo "   (contact method exists already)"
  aws lightsail put-alarm --alarm-name "$NAME-status" --monitored-resource-name "$NAME" \
    --metric-name StatusCheckFailed --comparison-operator GreaterThanOrEqualToThreshold --threshold 1 \
    --evaluation-periods 2 --datapoints-to-alarm 2 --treat-missing-data breaching \
    --contact-protocols Email --notification-triggers ALARM OK >/dev/null
  aws lightsail put-alarm --alarm-name "$NAME-cpu-credit" --monitored-resource-name "$NAME" \
    --metric-name BurstCapacityPercentage --comparison-operator LessThanOrEqualToThreshold --threshold 20 \
    --evaluation-periods 3 --datapoints-to-alarm 3 --contact-protocols Email --notification-triggers ALARM >/dev/null
fi

cat <<EOF

== $NAME is booting at $IP (first boot installs Docker and clones the repo: about 5 minutes)
Next (docs/lightsail-pilot.md):
 2. DNS at your registrar:  A  app.kathachepta.com  $IP     A  api.kathachepta.com  $IP
                            A  kathachepta.com      $IP     A  www.kathachepta.com  $IP
                            A  kadachepta.com       $IP     A  www.kadachepta.com   $IP
 3. ${KEY_PAIR:+Your key pair $KEY_PAIR is on the instance. Put its private key path in the desktop .env:}${KEY_PAIR:-Download the default SSH key for $REGION (Lightsail console > Account > SSH keys), then in the desktop .env:}
      KC_SERVER_HOST=$IP
      KC_SERVER_SSH_KEY=${KEY_PAIR:+<path to the private key of $KEY_PAIR>}${KEY_PAIR:-C:\\Users\\<you>\\.ssh\\LightsailDefaultKey-$REGION.pem}
EOF
