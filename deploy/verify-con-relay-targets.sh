#!/bin/sh
set -eu
# These source containers are deliberately retained during migration. Fail
# closed before opening any tunnel if a later recreate changes their addresses.
node_address=$(docker inspect --format '{{(index .NetworkSettings.Networks "monitoring_default").IPAddress}}' monitoring-node-exporter)
cadvisor_address=$(docker inspect --format '{{(index .NetworkSettings.Networks "monitoring_default").IPAddress}}' monitoring-cadvisor)
test "$node_address" = 172.20.0.2
test "$cadvisor_address" = 172.20.0.3
