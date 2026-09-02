#!/usr/bin/env python3

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause-Clear

# This tool generates Container Device Interface (CDI) specification files as
# defined by the CNCF Container Device Interface project:
#
#   https://github.com/cncf-tags/container-device-interface
#
# The generated JSON files follow the CDI spec format (see the CDI_VERSION
# below) and can be validated with the upstream 'cdi' tool from that project.

# Allow PEP 585/604 annotations (list[str], int | None) on Python 3.8/3.9.
from __future__ import annotations

import glob
import json
from pathlib import Path
import re
import stat
import sys
import logging
import argparse

known_classes = ['gpu', 'v4l2', 'dmaheap', 'fastrpc-cdsp', 'fastrpc-adsp']

# CDI specification version emitted in every generated spec file. See the CNCF
# Container Device Interface project for the format definition:
# https://github.com/cncf-tags/container-device-interface
CDI_VERSION = "0.6.0"

# CDI vendor namespace prefixed to every generated 'kind' (e.g. qualcomm.com/gpu)
CDI_VENDOR = "qualcomm.com"

def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(format="%(levelname)s: %(message)s", level=level)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Qualcomm CDI and hook script")
    parser.add_argument("-d", "--destdir", default="/", help="Destination root directory (default: %(default)s)")
    parser.add_argument("-H", "--hookfilename", default="vendorhook", help="Hook script filename (default: %(default)s)")
    parser.add_argument("-c", "--cdifilename", default="qualcomm.json", help="CDI JSON filename base; the device class is inserted before the extension, e.g. qualcomm.json -> qualcomm-gpu.json (default: %(default)s)")
    parser.add_argument("-C", "--classes", default=None, help="Comma-separated list of CDI classes to generate (default: all). Available: %s" % ", ".join(known_classes))
    parser.add_argument("-n", "--dry-run", action="store_true", help="Parse and probe devices but do not write any files")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    return parser.parse_args()

def find_devicenodes(deviceglob: str) -> list[str]:
    logging.debug("Globbing device nodes: %s", deviceglob)
    files = glob.glob(deviceglob)
    logging.info("Found %d nodes for pattern %s", len(files), deviceglob)
    logging.debug("Nodes for %s: %s", deviceglob, files)
    return files

def generate_devicenodes_cdi(nickname: str, filesglob: list[str]) -> list[dict]:
    if filesglob:
        logging.info("Generating CDI entries for '%s' with %d node(s)", nickname, len(filesglob) if filesglob else 0)
        filesglob_set = set(filesglob)

        # -secure nodes whose non-secure parent is also present are handled as siblings of
        # that parent entry, not as independent top-level entries
        def is_sibling(node: str) -> bool:
            return node.endswith('-secure') and node[:-len('-secure')] in filesglob_set

        def node_paths(node: str) -> list[dict]:
            # deviceNodes entries for one node: the node itself, plus its -secure
            # sibling when this is a cdsp/adsp node and that sibling is present.
            paths = [{"path": node}]
            if node.endswith(('cdsp', 'adsp')):
                securepath = node + "-secure"
                if securepath in filesglob_set:
                    logging.debug("DSP node detected, adding -secure variant for %s", node)
                    paths.append({"path": securepath})
            return paths

        # Count only nodes that will produce their own CDI entry
        effective_count = sum(1 for n in filesglob if not is_sibling(n))

        devicenodelist = []
        devicenodeindex = 0
        for devicenode in sorted(filesglob):
            if is_sibling(devicenode):
                continue
            device_pathlist = { "deviceNodes": node_paths(devicenode) }
            cdi_index = get_devicenode_index(devicenode)
            # If there's only one match *and* it doesn't have its own index, don't add the '0' index
            if effective_count == 1 and cdi_index is None:
                # Empty string means str(cdi_index) appends nothing, giving just 'nickname'
                cdi_index = ""
            # Reuse the devicenode index if present, otherwise generate our own
            if cdi_index is not None:
                # cdi_index is either an int parsed from the node name or "" (single unnamed node)
                device_entry = { "name": nickname+str(cdi_index), "containerEdits": device_pathlist }
            else:
                # No index in the node name and multiple nodes: fall back to a sequential counter
                device_entry = { "name": nickname+str(devicenodeindex), "containerEdits": device_pathlist }
            logging.debug("CDI device entry: %s", device_entry)
            devicenodelist.append(device_entry)
            devicenodeindex += 1

        # Build a catch-all entry that exposes every node in this class at once;
        # useful when a container needs the full set without listing them individually
        device_paths = []
        for devicenode in sorted(filesglob):
            if is_sibling(devicenode):
                continue
            # Reuse the per-device logic so cdsp-secure/adsp-secure is also in :all
            device_paths.extend(node_paths(devicenode))
        device_pathlist = { "deviceNodes":  device_paths  }
        device_entrys = { "name": nickname+":all", "containerEdits": device_pathlist }
        logging.debug("CDI catch-all entry: %s", device_entrys)
        devicenodelist.append(device_entrys)
    else:
        devicenodelist = []
        logging.debug("No nodes found for '%s'; no CDI entries generated", nickname)
    return devicenodelist

def get_devicenode_index(nodename: str) -> int | None:
    # Extract a trailing integer from the node name (e.g. 128 from 'renderD128')
    nodeindex = re.search(r'\d+$', nodename)
    return int(nodeindex.group()) if nodeindex else None

def build_cdi_spec(cdiclass: str, devices: list[dict], hookfilename: str,
                   enventries: list[str], mountentries: list[dict | None]) -> dict:
    """Assemble a single CDI specification dict for one device class.

    The returned structure follows the CDI spec format defined by the CNCF
    Container Device Interface project:
        https://github.com/cncf-tags/container-device-interface

    cdiclass:     device class name, suffixed onto CDI_VENDOR for the 'kind'
    devices:      list of CDI device entries (as built by generate_devicenodes_cdi)
    hookfilename: basename of the createContainer hook script under /bin
    enventries:   list of "KEY=value" strings added to containerEdits.env
    mountentries: list of mount dicts; only attached for fastrpc classes

    This function is pure (no filesystem access) so the generated spec can be
    validated by the upstream 'cdi' tool in the unit tests.
    """
    cdi = {"cdiVersion": CDI_VERSION, "kind": CDI_VENDOR + "/" + cdiclass}
    cdi["devices"] = devices
    container_edits = {"hooks": [{"hookName": "createContainer", "path": "/bin/" + hookfilename}],
                       "env": enventries}
    # Only bind-mount DSP firmware and devicetree for fastrpc device classes,
    # as those are the only classes that use Hexagon binaries
    if "fastrpc" in cdiclass:
        # filter(None, ...) strips any None placeholders left in the pre-allocated list
        container_edits["mounts"] = list(filter(None, mountentries))
    cdi["containerEdits"] = container_edits
    return cdi

def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logging.info("Starting Qualcomm CDI generation")
    logging.info("Config: destdir=%s, hookfilename=%s, cdifilename=%s, dry_run=%s", args.destdir, args.hookfilename, args.cdifilename, args.dry_run)

    if args.classes is not None:
        requested = [c.strip() for c in args.classes.split(',')]
        unknown = [c for c in requested if c not in known_classes]
        if unknown:
            print("Error: unknown class(es): %s" % ", ".join(unknown), file=sys.stderr)
            print("Available classes: %s" % ", ".join(known_classes), file=sys.stderr)
            return 1
        enabled_classes = requested
    else:
        enabled_classes = known_classes

    # Use CLI-configured values
    destdir = args.destdir
    hookfilename = args.hookfilename
    cdifilename = args.cdifilename

    # Find rendernodes and create entries for them
    rendernodes = find_devicenodes('/dev/dri/renderD*')
    render_cdi = generate_devicenodes_cdi('renderD', rendernodes)

    # Find all videonoodes and generate entries
    # TODO: add input/output filters to make selecting between encoders, decoders and cameras easier
    videonodes = find_devicenodes('/dev/video*')
    video_cdi = generate_devicenodes_cdi('video', videonodes)

    # Check for DMA heap
    dmaheaps = find_devicenodes('/dev/dma_heap/*system')
    dmaheap_cdi = generate_devicenodes_cdi('dmaheap-system', dmaheaps)

    # Check for DSP nodes
    cdsps = find_devicenodes('/dev/fastrpc-cdsp*')
    cdsps_cdi = generate_devicenodes_cdi('fastrpc-cdsp', cdsps)

    adsps = find_devicenodes('/dev/fastrpc-adsp*')
    adsps_cdi = generate_devicenodes_cdi('fastrpc-adsp', adsps)

    # Host-side helpers
    # TODO: generate helper scripts based the results of the above probes
    # Only chmod nodes for classes that are actually being generated, so
    # --classes keeps the hook script in sync with the written CDI files.
    nodes_by_class = {
        'gpu':          rendernodes,
        'v4l2':         videonodes,
        'dmaheap':      dmaheaps,
        'fastrpc-cdsp': cdsps,
        'fastrpc-adsp': adsps,
    }
    allnodes = [n for c, nodes in nodes_by_class.items() if c in enabled_classes for n in nodes]
    logging.info("Total nodes aggregated for hook: %d", len(allnodes))

    # Bind mounts into container
    # The primary use case is passing tightly coupled files into the
    # container, notably Hexagon binaries. The Hexagon binaries are
    # tightly coupled to the files loaded by the in-kernel firmware
    # loader. To lower the chance of a mismatch, Hexagon binaries found
    # on the host will be bind mounted automatically
    # Bind mount devicetree model if present
    devicetreefound = 0
    dtmodelstring = None
    # glob.glob() always returns a list; check for non-empty to confirm the file exists
    dtmodel = glob.glob("/sys/firmware/devicetree/base/model")
    if dtmodel:
        devicetreefound = 1
        dtmodelmount ={"hostPath": "/sys/firmware/devicetree/base/model" , "containerPath": "/run/device-model", "options": ["nosuid", "ro", "bind"]}
        modeldtnode = open("/sys/firmware/devicetree/base/model", "r")
        # remove literal Null terminator during read
        dtmodelstring = str(modeldtnode.read()).replace('\u0000', '')
        logging.info("Detected %s from devicetree", dtmodelstring)
        modeldtnode.close()

    # Glob for Hexagon DSP firmware directories; the four wildcard levels match
    # vendor/package/version/arch sub-paths under /usr/share
    localfiles = find_devicenodes('/usr/share/*/*/*/*/dsp/')
    mountentries = [None] * (len(localfiles) + devicetreefound)
    mountentry = 0
    for localfile in localfiles:
        mountentries[mountentry] ={"hostPath": localfile , "containerPath": localfile, "options": ["nosuid", "ro", "bind"]}
        mountentry += 1
    if devicetreefound > 0:
        mountentries[mountentry] = dtmodelmount


    enventries = []
    if dtmodelstring is not None:
        enventries = [ "MACHINE_NAME=" + dtmodelstring ]

    # Generate hookscript that runs during createContainer
    hookscriptbindir = Path(destdir).joinpath('bin')
    hookscriptpath = Path(hookscriptbindir).joinpath(hookfilename)
    if args.dry_run:
        logging.info("Dry run: skipping hook script write to %s", hookscriptpath)
    else:
        Path(hookscriptbindir).mkdir(parents=True, exist_ok=True)
        with open( hookscriptpath, "w") as hookscript:
            hookscript.write("#!/bin/bash\n\n")
            hookscript.write("# This script has been autogenerated by %s\n" % __file__)
            hookscript.write("# Changes made to this file directly *will* be lost\n\n")
            hookscript.write("for node in " + " ".join(allnodes) + " ; do \n\tchmod 0666 ${node}\ndone\n")
        hookscript.close()
        hookscriptpath.chmod(hookscriptpath.stat().st_mode | stat.S_IEXEC)
        logging.info("Wrote hook script: %s", hookscriptpath)

    # Write one CDI json per device class
    cdi_sections = [
        ('gpu',          render_cdi),
        ('v4l2',         video_cdi),
        ('dmaheap',      dmaheap_cdi),
        ('fastrpc-cdsp', cdsps_cdi),
        ('fastrpc-adsp', adsps_cdi),
    ]
    cdi_sections = [(c, d) for c, d in cdi_sections if c in enabled_classes]
    dynamiccdidir = Path(destdir).joinpath('run/cdi')
    cdifilename_stem = Path(cdifilename).stem
    cdifilename_suffix = Path(cdifilename).suffix

    # Older versions wrote a single monolithic CDI file (e.g. qualcomm.json); we
    # now write one file per device class (qualcomm-gpu.json, ...). Remove any
    # leftover monolithic file so it cannot define conflicting/stale devices
    # alongside the per-class files.
    legacy_cdi = dynamiccdidir.joinpath(cdifilename)
    if legacy_cdi.is_file():
        if args.dry_run:
            logging.info("Dry run: would remove old style monolithic CDI %s", legacy_cdi)
        else:
            logging.warning("Old style monolithic CDI detected, removing %s", legacy_cdi)
            legacy_cdi.unlink()

    for cdiclass, devices in cdi_sections:
        section_filename = "%s-%s%s" % (cdifilename_stem, cdiclass, cdifilename_suffix)
        cdipath = dynamiccdidir.joinpath(section_filename)
        if not devices:
            if cdipath.is_file():
                if args.dry_run:
                    logging.info("Dry run: would remove stale CDI JSON for '%s': %s", cdiclass, cdipath)
                else:
                    cdipath.unlink()
                    logging.info("Removed stale CDI JSON for '%s': %s", cdiclass, cdipath)
            else:
                logging.debug("Skipping CDI file for '%s': no devices", cdiclass)
            continue
        cdi = build_cdi_spec(cdiclass, devices, hookfilename, enventries, mountentries)
        if args.dry_run:
            logging.info("Dry run: skipping CDI JSON write to %s", cdipath)
        else:
            Path(dynamiccdidir).mkdir(parents=True, exist_ok=True)
            with open(cdipath, "w") as cdifile:
                cdifile.write(json.dumps(cdi))
            logging.info("Wrote CDI JSON: %s", cdipath)

    logging.info("Completed Qualcomm CDI generation")
    return 0

if __name__ == "__main__":
    sys.exit(main())
