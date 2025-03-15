"""
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
"""

import datetime
import ipaddress
import hashlib
import struct
import os
import json
import time
p4 = bfrt.gandalf.pipe
bf_port = bfrt.port.port
pre = bfrt.pre

logfile = "/home/tofino/gandalf.log"


egress_port = 66 #This is the egress port we want to multiply to

#Will contain a list of ports. Index is front_panel, value is the port's DEV_PORT number
port_mapping = [
]
ports_network = [2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32] #These should do timestamping

mcRules = [
	{
	"mgid":1,
	"egressPort":egress_port,
	"amount": 1
	},
	{
	"mgid":2,
	"egressPort":egress_port,
	"amount": 10
	}
]


def log(text):
	global logfile, datetime
	line = "%s \t GandalfCPU: %s" %(str(datetime.datetime.now()), str(text))
	print(line)
	
	f = open(logfile, "a")
	f.write(line + "\n")
	f.close()

def digest_callback(dev_id, pipe_id, direction, parser_id, session, msg):
	global p4, log, Digest
	#smac = p4.Ingress.smac
	#log("Received message from data plane!")
	for dig in msg:
		log("Digest: %s" %str(dig))
	
	return 0

def bindDigestCallback():
	global digest_callback, log, p4
	
	try:
		p4.SwitchIngressDeparser.debug_digest.callback_deregister()
	except:
		pass
	finally:
		log("Deregistering old digest callback function (if any)")

	#Register as callback for digests (bind to DMA?)
	log("Registering digest callback...")
	p4.SwitchIngressDeparser.debug_digest.callback_register(digest_callback)

	log("Bound callback to digest")

#NOTE: this might break ALL rules about multicasting. Very hacky. This is used for packet duplication to increase DUT load
def configMulticasting():
	global p4, pre, log, port_mapping
	log("Configuring multicasting for duplication...")
	
	lastNodeID=0
	
	num_ports = 127
	max_duplications = 8
	
	mgid_last = 0
	nodeID_last=0
	
	#This is a list of supported number of duplicates
	#list_num_duplicates = [2,4,8,10]
	list_num_duplicates = [1,2,3,4,5,6,7,8,9,10]
	
	
	
	for egrPort_panel in range(1,num_ports+1,1):
		egrPort_dp = port_mapping[egrPort_panel]
		
		#If the port exists, then configure multicast rules
		if egrPort_dp is not None:
			
			#Create multicast groups for this port, one per duplication level
			for num_duplicates in list_num_duplicates:
				mgid_last = mgid_last+1
				mgid = mgid_last
				
				log("Creating a multicast rule for egress port %i (FP%i) and %i duplications..." %(egrPort_dp, egrPort_panel, num_duplicates))
				
				nodeIDs = []
				#log("Adding multicast nodes (one for each duplication)...")
				for i in range(num_duplicates):
					nodeID_last += 1
					#log("Creating node %i" %nodeID_last)
					pre.node.add(DEV_PORT=[egrPort_dp], MULTICAST_NODE_ID=nodeID_last)
					nodeIDs.append(nodeID_last)
				
				log("Multicast nodes created. Creating the multicast group... ID %i" %mgid)
				pre.mgid.add(MGID=mgid, MULTICAST_NODE_ID=nodeIDs, MULTICAST_NODE_L1_XID=[0]*num_duplicates, MULTICAST_NODE_L1_XID_VALID=[False]*num_duplicates)
				
				#log("Inserting into the duplication M/A table")
				p4.SwitchIngress.tbl_duplication.add_with_set_multicast(egress_port=egrPort_dp, num_duplicates=num_duplicates, mcast_grp=mgid)
			
			#Set port duplication level as default to 1
			p4.SwitchIngress.tbl_getDuplicationLevel.add_with_set_duplication_level(egress_port=egrPort_dp, num_duplicates=1)
			
			'''
			default_duplication_level_toDUT = 10 #Towards the DUT will default to duplication level 10
			default_duplication_level_toTG = 1 #Back to the TG will not do duplication
			if egrPort_panel in ports_network:
				p4.SwitchIngress.tbl_getDuplicationLevel.add_with_set_duplication_level(egress_port=egrPort_dp, num_duplicates=default_duplication_level_toDUT)
			else:
				p4.SwitchIngress.tbl_getDuplicationLevel.add_with_set_duplication_level(egress_port=egrPort_dp, num_duplicates=default_duplication_level_toTG)
			'''

#This will configure wire pairs (1,2),(3,4),(5,6) and so on
def insertForwardingRules():
	global p4, log, ipaddress
	
	wire_pairs = []
	
	log("Will define wire pairs following the port mapping. Will connect 1-2, 3-4, and so on. Lower port is host, upper is network.")
	
	for host_port in range(1, 64, 2):
		try:
			network_port = host_port+1
			host_port_dp = port_mapping[host_port]
			network_port_dp = port_mapping[network_port]
			
			#Skip over non-existant port pairs
			if host_port_dp is None or network_port_dp is None:
				continue
			
			wire_pairs.append( {"host":host_port_dp, "network":network_port_dp} )
		except:
			pass
	
	log("Inserting forwarding rules...")
	
	for pair in wire_pairs:
		host_port = pair["host"]
		network_port = pair["network"]
		
		log("Configuring forwarding for pair (%i,%i)" %(host_port, network_port))
		
		p4.SwitchIngress.tbl_portfwd.add_with_forward(ingress_port=host_port, egress_port=network_port) #Forwarding from host to network
		p4.SwitchIngress.tbl_portfwd.add_with_forward(ingress_port=network_port, egress_port=host_port) #Forwarding from network to host

def getPortMapping():
	import time
	global log, bf_port
	
	log("Getting the port mapping")
	
	port_DPs = [None]*128 #this will keep a list of all dev_port
	
	for dev_port in range(192): #>192 throws a SIGFAULT
		log("Trying dev_port %i..." %(dev_port))
		
		if dev_port == 68:
			log("Skipping 68. Shown to cause SEGFAULT on some switches")
			continue
		
		try:
			time.sleep(0.05)
			ret = bf_port.get(DEV_PORT=dev_port)
			items = ret.data.items
			port_name = None
			#Iterate over all items in this port entry, finding PORT_NAME
			for key,value in items():
				if "PORT_NAME" in str(key):
					port_name = value
					break
			
			panel_port = int(str(port_name).split("/")[0])
			subport = int(str(port_name).split("/")[1])
			
			if panel_port == 33: #This is CPU port
				log("This is a CPU port")
				panel_port = 100+subport
			else:
				if subport != 0:
					log("Panel port %i has a subport %i! We do not yet support these mappings!" %(panel_port, subport))
			
			log("Got panel port for DP %i. Panel port is %i" %(dev_port, panel_port))
			
			port_DPs[panel_port] = dev_port
		
		except:
			pass #The DP likely did not exist
	
	log("Done retrieving all dev ports.")
	print(port_DPs)
	return port_DPs

def setTimestamping(port_fp, doIngressTimestamp=True, doEgressTimestamp=True):
	global p4, log, port_mapping
	port_dp = port_mapping[port_fp]
	log("Configuring timestamping for port %i (FP%i). Ingress:%s, Egress:%s" %(port_dp, port_fp, str(doIngressTimestamp), str(doEgressTimestamp)))
	
	#Ensure no timestamping enabled for this port initially
	try:
		p4.SwitchIngress.tbl_timestamping.delete(ingress_port=port_dp)
	except:
		pass
	try:
		p4.SwitchEgress.tbl_timestamping.delete(egress_port=port_dp)
	except:
		pass
	
	#Then conditionally enable timestamping
	if doIngressTimestamp:
		p4.SwitchIngress.tbl_timestamping.add_with_insertTimestamp_2(ingress_port=port_dp) #Enable ingress timestamping
	if doEgressTimestamp:
		p4.SwitchEgress.tbl_timestamping.add_with_insertTimestamp_1(egress_port=port_dp) #Enable egress timestamping

def setDuplicationLevel(egress_port_panel, duplication_level=1):
	global p4, log, port_mapping
	
	log("Setting duplication level of FP port %i to %i" %(egress_port_panel, duplication_level))
	
	#supported_duplevels = [1,2,4,8,10]
	supported_duplevels = [1,2,3,4,5,6,7,8,9,10]
	
	assert duplication_level in supported_duplevels, "Unsupported duplication level. Currently only set up PRE for %s" %str(supported_duplevels)
	
	egress_port_dp = port_mapping[egress_port_panel]
	log("Removing old entry in table...")
	p4.SwitchIngress.tbl_getDuplicationLevel.delete(egress_port=egress_port_dp)
	
	log("Inserting new entry in table...")
	p4.SwitchIngress.tbl_getDuplicationLevel.add_with_set_duplication_level(egress_port=egress_port_dp, num_duplicates=duplication_level)

#Thanks to Sebastian Stöcker for base ASCII art of Gandalf
def printArt():
	log(r"""
                             
                        ,---.
 One ping to           /    |
 rule them all        /     |
   -Gandalf          /      |
   -MICHAEL SCOTT    /       |
               _´_,'        |
         \   <  -'          :
          \   `-.__..--'``-,_\_
                 |o/ ` :,.)_`>
                 :/ `     ||/)
                 (_.).__,-` |\
                 /( `.``   `| :
                 \'`-.)  `  ; ;
                 | `       /-<
                 |     `  /   `.
 ,-_-..____     /|  `    :__..-'\
/,'-.__\\  ``-./ :`      ;       \
`\ `\  `\\  \ :  (   `  /  ,   `. \
  \` \   \\   |  | `   :  :     .\ \
   \ `\_  ))  :  ;     |  |      ): :
  (`-.-'\ ||  |\ \   ` ;  ;       | |
   \-_   `;;._   ( `  /  /_       | |
    `-.-.// ,'`-._\__/_,'         ; |
       \:: :     /     `     ,   /  |
        || |    (        ,' /   /   |
        ||                ,'   /    |

	""")

def bootstrap():
	import time
	global log, port_mapping, getPortMapping, bindDigestCallback, insertForwardingRules, configMulticasting
	
	log("Bootstrapping GANDaLF")
	
	time.sleep(2)
	port_mapping = getPortMapping()
	
	bindDigestCallback()
	
	
	insertForwardingRules()
	configMulticasting()
	
	log("Bootstrap complete")
	


bootstrap()

printArt()

print("The switch is now a transparent wire for all port pairs (1,2) (3,4) ...")
print("************************************************")
print("  Usage Guide:  ")
print("************************************************")
print("Here you can configure packet timestamping and duplication per-port.")
print("Ports should be entered as INTEGERS, matching the front panel.")
print()
print(" * Timestamping * (Configure per-port timestamp insertion)")
print("setTimestamping(PORT,INGRESS_ENABLED,EGRESS_ENABLED)")
print("Examples:")
print(" - Enable bi-directional timestamping on port 2: setTimestamping(2)")
print(" - Enable only Ingress timestamping on port 2: setTimestamping(2,True,False)")
print(" - Disable timestamping on port 2: setTimestamping(2,False,False)")
print()
print(" * Duplication * (Configure per-port packet duplication)")
print("setDuplicationLevel(PORT,DUPLICATIONLEVEL)")
print("Examples:")
print(" - Duplicate packets egressing port 4 by x10: setDuplicationLevel(4,10)")
print(" - Disable duplication on port 4: setDuplicationLevel(4)")
print("************************************************")
print("First, to enable configuration commands, run: 'bfrt' below.")

#
# Here you can add commands that you want to automatically run every time the GANDaLF bootstraps
#

#Enable bi-directional timestamping on ports 2 and 4
#setTimestamping(2)
#setTimestamping(4)

#Set x10 packet duplication on ports 2 and 4 egress
#setDuplicationLevel(2, 10)
#setDuplicationLevel(4, 10)

bfrt
