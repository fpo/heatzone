#!/usr/bin/env bash

scp -O -P 22222 -r /Users/Frank/VS_heatzone/custom_components/heatzone/* root@pi5.internal:/mnt/data/supervisor/homeassistant/custom_components/heatzone

