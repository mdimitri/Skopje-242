#!/bin/bash
# NAT lab: two home networks (both 192.168.1.0/24) behind their own NAT routers on a fake internet, run as root (Linux netns).
#   lab.sh <nat: cone|symmetric|mixed (host normal, guest symmetric)> <wifi loss probability per router, e.g. 0.05, or none> <talk seconds>
set -e
NAT=${1:-cone}; WIFI=${2:-none}; TALK=${3:-8}
D=$(cd "$(dirname "$0")" && pwd)
rm -f /tmp/natlab_code /tmp/natlab_word
for n in inet r1 r2 pc1 pc2; do ip netns del $n 2>/dev/null || true; done
for n in inet r1 r2 pc1 pc2; do ip netns add $n; ip -n $n link set lo up; done
ip -n inet link add br0 type bridge; ip -n inet addr add 203.0.113.1/24 dev br0; ip -n inet addr add 203.0.113.2/24 dev br0; ip -n inet link set br0 up
for i in 1 2; do
  ip link add w$i netns r$i type veth peer name b$i netns inet
  ip -n inet link set b$i master br0; ip -n inet link set b$i up
  ip -n r$i addr add 203.0.113.1$i/24 dev w$i; ip -n r$i link set w$i up
  ip link add l$i netns r$i type veth peer name e$i netns pc$i
  ip -n r$i addr add 192.168.1.1/24 dev l$i; ip -n r$i link set l$i up
  ip -n pc$i addr add 192.168.1.10/24 dev e$i; ip -n pc$i link set e$i up
  ip -n pc$i route add default via 192.168.1.1
  ip netns exec r$i sysctl -qw net.ipv4.ip_forward=1
  if [ "$NAT" = symmetric ] || { [ "$NAT" = mixed ] && [ $i = 2 ]; }; then
    ip netns exec r$i iptables -t nat -A POSTROUTING -o w$i -j MASQUERADE --random-fully
  else
    ip netns exec r$i iptables -t nat -A POSTROUTING -o w$i -j MASQUERADE
  fi
  ip netns exec r$i iptables -A FORWARD -i w$i -m state --state NEW -j DROP     # home router: nothing unsolicited comes in
  ip netns exec r$i iptables -A INPUT -i w$i -m state --state NEW -j DROP
  if [ "$WIFI" != none ]; then          # lossy WiFi: drop this share of packets both ways (no netem in this kernel)
    ip netns exec r$i iptables -I FORWARD -p udp -m statistic --mode random --probability $WIFI -j DROP
  fi
done
ip netns exec inet python3 -u "$D/servers.py" 203.0.113.1 203.0.113.2 > /tmp/natlab_srv.log 2>&1 &
SRV=$!
sleep 1
ip netns exec pc1 python3 "$D/peer.py" host 203.0.113.1 $TALK > /tmp/natlab_host.out 2>&1 &
H=$!
sleep 3
ip netns exec pc2 env CODE=$CODE WORD=$WORD python3 "$D/peer.py" guest 203.0.113.1 $TALK > /tmp/natlab_guest.out 2>&1 || true
wait $H || true
kill $SRV 2>/dev/null || true
tail -1 /tmp/natlab_host.out; tail -1 /tmp/natlab_guest.out
for n in inet r1 r2 pc1 pc2; do ip netns del $n 2>/dev/null || true; done
