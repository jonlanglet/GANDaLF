/*
MIT License

Copyright (c) 2025 Jonatan Langlet

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/

#include <core.p4>
#include <tna.p4>

#define ETHERTYPE_IPV4 0x0800
#define ETHERTYPE_ARP 0x0806

typedef bit<48> mac_address_t;
typedef bit<32> ipv4_address_t;
typedef bit<8> debug_t;

//#define DO_DEBUG //Uncomment this line to enable debug digest generation. Avoid this during evaluation

//DEBUG() only does something if DO_DEBUG is defined
#ifdef DO_DEBUG
	#define DEBUG(i) ig_md.debug = (debug_t)i;
#else
	#define DEBUG(i)
#endif

//14 bytes
header ethernet_h
{
	bit<48> dstAddr;
	bit<48> srcAddr;
	bit<16> etherType;
}

header arp_h
{
	bit<16> hwType; //0x0001 for ethernet
	bit<16> proto; //0x0800 for IPv4
	bit<8> hwSize;
	bit<8> protoSize;
	bit<16> opcode;
	mac_address_t srcEthAddr;
	ipv4_address_t srcIPAddr;
	mac_address_t dstEthAddr;
	ipv4_address_t dstIPAddr;
}

struct debug_digest_ingress_t
{
	debug_t debug;
	PortId_t ingress_port;
	PortId_t egress_port;
	bit<1> timestamp2_inserted;
}

struct ingress_metadata_t
{
	debug_t debug;
	bit<1> send_debug_data;
	bit<1> is_multiplying;
	PortId_t ingress_port;
	PortId_t egress_port;
	bit<8> num_duplicates;
	bit<1> timestamp2_inserted;
}
struct egress_metadata_t
{
	
}

struct headers
{
	ethernet_h ethernet;
	arp_h arp;
}

parser TofinoIngressParser(packet_in pkt, inout ingress_metadata_t ig_md, out ingress_intrinsic_metadata_t ig_intr_md)
{
	state start
	{
		pkt.extract(ig_intr_md);
		transition select(ig_intr_md.resubmit_flag)
		{
			1 : parse_resubmit;
			0 : parse_port_metadata;
		}
	}

	state parse_resubmit
	{
		transition reject;
	}

	state parse_port_metadata
	{
		pkt.advance(64); //Tofino 1
		transition accept;
	}
}

parser SwitchIngressParser(packet_in pkt, out headers hdr, out ingress_metadata_t ig_md, out ingress_intrinsic_metadata_t ig_intr_md)
{
	TofinoIngressParser() tofino_parser;

	state start 
	{
		tofino_parser.apply(pkt, ig_md, ig_intr_md);
		
		ig_md.send_debug_data = 0;
		ig_md.is_multiplying = 0;
		ig_md.timestamp2_inserted = 0;
		ig_md.ingress_port = ig_intr_md.ingress_port;
		
		transition parse_ethernet; //No parsing required in ingress
	}
	
	state parse_ethernet
	{
		pkt.extract(hdr.ethernet);
		transition select(hdr.ethernet.etherType)
		{
			ETHERTYPE_ARP: parse_arp;
			default: accept;
		}
	}
	
	state parse_arp
	{
		pkt.extract(hdr.arp);
		
		transition accept;
	}
}

control ControlMultiplication(inout headers hdr, inout ingress_metadata_t ig_md, in ingress_intrinsic_metadata_t ig_intr_md, inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md)
{
	apply
	{
		//Disabled for now, until we need it and discuss specifics
		//tbl_lookupMultiplication.apply();
	}
}

control SwitchIngress(inout headers hdr, inout ingress_metadata_t ig_md, in ingress_intrinsic_metadata_t ig_intr_md, in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md, inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md, inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md)
{
	ControlMultiplication() Multiplication;
	
	action forward(PortId_t egress_port)
	{
		ig_intr_tm_md.ucast_egress_port = egress_port; //Set egress port
		ig_md.egress_port = egress_port;
		DEBUG(egress_port)
	}
	action drop()
	{
		ig_intr_dprsr_md.drop_ctl = 1;
	}
	table tbl_portfwd
	{
		key = {
			ig_intr_md.ingress_port: exact;
		}
		actions = {
			forward;
			NoAction;
			drop;
		}
		size=128;
		default_action = drop();
	}
	
	//Write the timestamp into the packet
	action insertTimestamp_2()
	{
		hdr.ethernet.dstAddr = ig_intr_md.ingress_mac_tstamp;
		ig_md.timestamp2_inserted = 1;
	}
	table tbl_timestamping
	{
		key = {
			ig_intr_md.ingress_port: exact;
		}
		actions = {
			insertTimestamp_2;
			NoAction;
		}
		size=128;
		default_action = NoAction();
	}
	
	
	//Table to perform duplication through single-destination multicasting
	action set_multicast(bit<16> mcast_grp)
	{
		ig_intr_tm_md.mcast_grp_a = mcast_grp;
		ig_intr_tm_md.ucast_egress_port = 0; //We should then disable unicast egress (otherwise one too many packets)
		ig_md.is_multiplying = 1;
		DEBUG(mcast_grp)
	}
	table tbl_duplication
	{
		key = {
			ig_md.egress_port: exact;
			ig_md.num_duplicates: exact;
		}
		actions = {
			set_multicast;
			NoAction;
		}
		size=4096;
	}
	
	//Table to set duplication level
	action set_duplication_level(bit<8> num_duplicates)
	{
		ig_md.num_duplicates = num_duplicates;
	}
	table tbl_getDuplicationLevel
	{
		key = {
			ig_md.egress_port: exact;
		}
		actions = {
			set_duplication_level;
			NoAction;
		}
		size=128;
	}
	
	apply
	{
		//Always apply the normal forwarding table
		tbl_portfwd.apply();
		
		//GANDaLF will not modify ARP packets
		if(!hdr.arp.isValid())
		{
			//Then do conditional duplication (egress port will be part of the key to decide multicast group)
			//ig_md.num_duplicates = 10; //This will determine how many packet duplicates are created
			tbl_getDuplicationLevel.apply();
			tbl_duplication.apply();
			
			//Will insert a timestamp if the ingress port is from the DUT
			tbl_timestamping.apply();
		}
		
		#ifdef DO_DEBUG
			ig_md.send_debug_data = 1;
		#endif
	}
}


control SwitchIngressDeparser(packet_out pkt, inout headers hdr, in ingress_metadata_t ig_md, in ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md)
{
	Digest<debug_digest_ingress_t>() debug_digest;
	apply
	{
		if( ig_md.send_debug_data == 1 )
		{
			debug_digest.pack({
				ig_md.debug,
				ig_md.ingress_port,
				ig_md.egress_port,
				ig_md.timestamp2_inserted
			});
		}
		
		pkt.emit(hdr);
	}
}

parser TofinoEgressParser(packet_in pkt, out egress_intrinsic_metadata_t eg_intr_md)
{
	state start
	{
		pkt.extract(eg_intr_md);
		transition accept;
	}
}

parser SwitchEgressParser(packet_in pkt, out headers hdr, out egress_metadata_t eg_md, out egress_intrinsic_metadata_t eg_intr_md)
{
	TofinoEgressParser() tofino_parser;

	state start
	{
		tofino_parser.apply(pkt, eg_intr_md);
		transition parse_ethernet;
	}
	
	state parse_ethernet
	{
		pkt.extract(hdr.ethernet);
		transition select(hdr.ethernet.etherType)
		{
			ETHERTYPE_ARP: parse_arp;
			default: accept;
		}
	}
	
	state parse_arp
	{
		pkt.extract(hdr.arp);
		
		transition accept;
	}
}

control SwitchEgress(inout headers hdr, inout egress_metadata_t eg_md, in egress_intrinsic_metadata_t eg_intr_md, in egress_intrinsic_metadata_from_parser_t eg_intr_from_prsr, inout egress_intrinsic_metadata_for_deparser_t eg_intr_md_for_dprsr, inout egress_intrinsic_metadata_for_output_port_t eg_intr_md_for_oport)
{
	//Write the timestamp into the packet, if enabled for the port
	action insertTimestamp_1()
	{
		hdr.ethernet.srcAddr = eg_intr_from_prsr.global_tstamp;
	}
	table tbl_timestamping
	{
		key = {
			eg_intr_md.egress_port: exact;
		}
		actions = {
			insertTimestamp_1;
			NoAction;
		}
		size=128;
		default_action = NoAction();
	}
	
	apply
	{
		//GANDaLF will not modify ARP
		if(!hdr.arp.isValid())
		{
			tbl_timestamping.apply();
		}
	}
}


control SwitchEgressDeparser(packet_out pkt, inout headers hdr, in egress_metadata_t eg_md, in egress_intrinsic_metadata_for_deparser_t eg_dprsr_md)
{
	apply
	{
		pkt.emit(hdr);
	}
}


Pipeline(SwitchIngressParser(),
	SwitchIngress(),
	SwitchIngressDeparser(),
	SwitchEgressParser(),
	SwitchEgress(),
	SwitchEgressDeparser()
) pipe;

Switch(pipe) main;
