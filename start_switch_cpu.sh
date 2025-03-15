#!/bin/bash

echo Starting the python switch_cpu script for GANDaLF

echo "INFO TO DEPLOYER! Make sure you update the paths"
$SDE/run_bfshell.sh -b /home/tofino/Gandalf/switch_cpu.py -i
