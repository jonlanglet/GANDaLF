#!/usr/bin/env python3

from scapy.all import *
from scapy.layers.l2 import Ether

def mac_to_int(mac):
	return int(mac.replace(":", ""), 16)

def parse_pcap(file_name):
	packets = rdpcap(file_name)

	for packet in packets:
		if Ether in packet:
			ether_layer = packet[Ether]
			src_mac = ether_layer.src
			dst_mac = ether_layer.dst
			
			timestamp_1 = mac_to_int(src_mac)
			timestamp_2 = mac_to_int(dst_mac)
			
			latency = timestamp_2 - timestamp_1
			print("Latency: %ins" %latency)

parse_pcap("ping_latencies.pcap")
