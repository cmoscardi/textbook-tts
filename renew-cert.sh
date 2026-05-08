#!/bin/bash
set -e

echo "REMINDER: Open port 80 in your firewall before continuing."
echo "Let's Encrypt needs to reach http://home.christianmoscardi.com on port 80 to complete the challenge."
echo ""
read -p "Press Enter once port 80 is open..."

sudo certbot renew
sudo systemctl reload nginx

echo "Done. Remember to close port 80 in your firewall."
