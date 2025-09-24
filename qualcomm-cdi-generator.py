#!/usr/bin/env python3

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause-Clear

import glob
import json
import sys

def find_devicenodes(deviceglob):
    files = glob.glob(deviceglob)
    return files

def generate_devicenodes_cdi(nickname, filesglob):
    rendernodeindex = 0
    rendernodelist = [None] * (len(filesglob) + 1)
    for rendernode in sorted(filesglob):
        gpu_path = {"path": rendernode} 
        gpu_pathlist = { "deviceNodes": [ gpu_path ] }
        device_gpu = { "name": nickname+str(rendernodeindex), "containerEdits": gpu_pathlist }
        print(device_gpu, file=sys.stderr)
        rendernodelist[rendernodeindex] = device_gpu
        rendernodeindex += 1

    catchallindex = 0
    gpu_paths = [None] * len(filesglob)
    for rendernode in sorted(filesglob):
        gpu_paths[catchallindex] = {"path": rendernode}
        catchallindex += 1
    gpu_pathlist = { "deviceNodes":  gpu_paths  }
    device_gpus = { "name": nickname+":all", "containerEdits": gpu_pathlist }
    rendernodelist[rendernodeindex] = device_gpus

    return rendernodelist

# Find rendernodes and create entries for them
rendernodes = find_devicenodes('/dev/dri/render*')
render_cdi = generate_devicenodes_cdi('render', rendernodes)

# Find all videonoodes and generate entries
# TODO: add input/output filters to make selecting between encoders, decoders and cameras easier
videonodes = find_devicenodes('/dev/video*')
video_cdi = generate_devicenodes_cdi('video', videonodes)

cdimain = { "cdiVersion": "0.6.0", "kind": "qualcomm.com/gpu"}
cdimain["devices"] = render_cdi + video_cdi 

print(json.dumps(cdimain))
