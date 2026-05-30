#!/bin/bash

iptables -I INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -I INPUT -i lo -j ACCEPT
iptables -I OUTPUT -o lo -j ACCEPT
iptables -I OUTPUT -m owner --uid-owner root -j ACCEPT  
iptables -I OUTPUT -m owner --uid-owner 42 -j ACCEPT  
iptables -I OUTPUT -m owner --uid-owner net_user -j ACCEPT
iptables -I OUTPUT -p udp --dport 53 -j ACCEPT
iptables -I OUTPUT -p tcp --dport 53 -j ACCEPT
iptables -A OUTPUT -j DROP
