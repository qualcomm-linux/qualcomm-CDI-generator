# Qualcomm CDI generator

Tooling to generate CDI config files to pass devices through to containers

## Branches

**main**: Primary development branch. Contributors should develop submissions based on this branch, and submit pull requests to this branch.

## Requirements

The main tool only requires python3 to generate a CDI. To consume it, you need a container runtime like podman or docker.

Recent versions of Podman (5.6.x) and Docker (28.3.x) work out of the box, for earlier Docker versions (26.x) you'll need a `/etc/docker/daemon.json` file:

```json
{
  "features": {
     "cdi": true
  },
  "cdi-spec-dirs": ["/etc/cdi/", "/run/cdi"]
}
```

For Docker 28.0.x only the feature enablement is needed:
```json
{
  "features": {
     "cdi": true
  }
}
```

Either restart the docker daemon or reboot to have this config take effect.

## Installation Instructions

Copy over `qualcomm-cdi-generator`

## Usage

On the target, run the CDI generator as root. The output directory `/run/cdi` is created automatically:

```shell
# qualcomm-cdi-generator
```

The tool probes the hardware, writes one CDI JSON file per device class under `/run/cdi`, and writes a hook script to `/bin/vendorhook`. Run with `-v` to see what was found and written, or `-vv` for full debug output.

### Command-line options

| Option | Long form | Default | Description |
|--------|-----------|---------|-------------|
| `-d` | `--destdir` | `/` | Root directory for all output paths |
| `-H` | `--hookfilename` | `vendorhook` | Hook script filename written under `<destdir>/bin/` |
| `-c` | `--cdifilename` | `qualcomm.json` | CDI filename base; the device class is inserted before the extension, e.g. `qualcomm.json` → `qualcomm-gpu.json` |
| `-C` | `--classes` | all | Comma-separated list of CDI classes to generate. Available: `gpu`, `v4l2`, `dmaheap`, `fastrpc-cdsp`, `fastrpc-adsp` |
| `-n` | `--dry-run` | off | Probe devices but do not write any files |
| `-v` | `--verbose` | off | Increase verbosity; use `-vv` for debug output |

### Example session

```shell
(cdi) root@ventunoq:~# qualcomm-cdi-generator -v
INFO: Starting Qualcomm CDI generation
INFO: Config: destdir=/, hookfilename=vendorhook, cdifilename=qualcomm.json, dry_run=False
INFO: Found 1 nodes for pattern /dev/dri/renderD*
INFO: Generating CDI entries for 'renderD' with 1 node(s)
INFO: Found 30 nodes for pattern /dev/video*
INFO: Generating CDI entries for 'video' with 30 node(s)
INFO: Found 1 nodes for pattern /dev/dma_heap/*system
INFO: Generating CDI entries for 'dmaheap-system' with 1 node(s)
INFO: Found 2 nodes for pattern /dev/fastrpc-cdsp*
INFO: Generating CDI entries for 'fastrpc-cdsp' with 2 node(s)
INFO: Found 1 nodes for pattern /dev/fastrpc-adsp*
INFO: Generating CDI entries for 'fastrpc-adsp' with 1 node(s)
INFO: Total nodes aggregated for hook: 35
INFO: Detected Arduino Monza from devicetree
INFO: Found 14 nodes for pattern /usr/share/*/*/*/*/dsp/
INFO: Wrote hook script: /bin/vendorhook
WARNING: Old style monolithic CDI detected, removing /run/cdi/qualcomm.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-gpu.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-v4l2.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-dmaheap.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-fastrpc-cdsp.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-fastrpc-adsp.json
INFO: Completed Qualcomm CDI generation
(cdi) root@ventunoq:~# docker info
[...]
Server:
 CDI spec directories:
  /etc/cdi
  /var/run/cdi
 Discovered Devices:
  cdi: qualcomm.com/dmaheap=dmaheap-system
  cdi: qualcomm.com/dmaheap=dmaheap-system:all
  cdi: qualcomm.com/fastrpc-adsp=fastrpc-adsp
  cdi: qualcomm.com/fastrpc-adsp=fastrpc-adsp:all
  cdi: qualcomm.com/fastrpc-cdsp=fastrpc-cdsp
  cdi: qualcomm.com/fastrpc-cdsp=fastrpc-cdsp:all
  cdi: qualcomm.com/gpu=renderD128
  cdi: qualcomm.com/gpu=renderD:all
  cdi: qualcomm.com/v4l2=video0
  cdi: qualcomm.com/v4l2=video1
  cdi: qualcomm.com/v4l2=video10
  cdi: qualcomm.com/v4l2=video11
  cdi: qualcomm.com/v4l2=video12
  cdi: qualcomm.com/v4l2=video13
  cdi: qualcomm.com/v4l2=video14
  cdi: qualcomm.com/v4l2=video15
  cdi: qualcomm.com/v4l2=video16
  cdi: qualcomm.com/v4l2=video17
  cdi: qualcomm.com/v4l2=video18
  cdi: qualcomm.com/v4l2=video19
  cdi: qualcomm.com/v4l2=video2
  cdi: qualcomm.com/v4l2=video20
  cdi: qualcomm.com/v4l2=video21
  cdi: qualcomm.com/v4l2=video22
  cdi: qualcomm.com/v4l2=video23
  cdi: qualcomm.com/v4l2=video24
  cdi: qualcomm.com/v4l2=video25
  cdi: qualcomm.com/v4l2=video26
  cdi: qualcomm.com/v4l2=video27
  cdi: qualcomm.com/v4l2=video28
  cdi: qualcomm.com/v4l2=video29
  cdi: qualcomm.com/v4l2=video3
  cdi: qualcomm.com/v4l2=video4
  cdi: qualcomm.com/v4l2=video5
  cdi: qualcomm.com/v4l2=video6
  cdi: qualcomm.com/v4l2=video7
  cdi: qualcomm.com/v4l2=video8
  cdi: qualcomm.com/v4l2=video9
  cdi: qualcomm.com/v4l2=video:all
[...]
(cdi) root@ventunoq:~# cdi classes
CDI device classes found:
  0. dmaheap (1 vendors: qualcomm.com)
  1. fastrpc-adsp (1 vendors: qualcomm.com)
  2. fastrpc-cdsp (1 vendors: qualcomm.com)
  3. gpu (1 vendors: qualcomm.com)
  4. v4l2 (1 vendors: qualcomm.com)
(cdi) root@ventunoq:~# cdi devices
CDI devices found:
  0. qualcomm.com/dmaheap=dmaheap-system
  1. qualcomm.com/dmaheap=dmaheap-system:all
  2. qualcomm.com/fastrpc-adsp=fastrpc-adsp
  3. qualcomm.com/fastrpc-adsp=fastrpc-adsp:all
  4. qualcomm.com/fastrpc-cdsp=fastrpc-cdsp
  5. qualcomm.com/fastrpc-cdsp=fastrpc-cdsp:all
  6. qualcomm.com/gpu=renderD128
  7. qualcomm.com/gpu=renderD:all
  8. qualcomm.com/v4l2=video0
  9. qualcomm.com/v4l2=video1
  10. qualcomm.com/v4l2=video10
  11. qualcomm.com/v4l2=video11
  12. qualcomm.com/v4l2=video12
  13. qualcomm.com/v4l2=video13
  14. qualcomm.com/v4l2=video14
  15. qualcomm.com/v4l2=video15
  16. qualcomm.com/v4l2=video16
  17. qualcomm.com/v4l2=video17
  18. qualcomm.com/v4l2=video18
  19. qualcomm.com/v4l2=video19
  20. qualcomm.com/v4l2=video2
  21. qualcomm.com/v4l2=video20
  22. qualcomm.com/v4l2=video21
  23. qualcomm.com/v4l2=video22
  24. qualcomm.com/v4l2=video23
  25. qualcomm.com/v4l2=video24
  26. qualcomm.com/v4l2=video25
  27. qualcomm.com/v4l2=video26
  28. qualcomm.com/v4l2=video27
  29. qualcomm.com/v4l2=video28
  30. qualcomm.com/v4l2=video29
  31. qualcomm.com/v4l2=video3
  32. qualcomm.com/v4l2=video4
  33. qualcomm.com/v4l2=video5
  34. qualcomm.com/v4l2=video6
  35. qualcomm.com/v4l2=video7
  36. qualcomm.com/v4l2=video8
  37. qualcomm.com/v4l2=video9
  38. qualcomm.com/v4l2=video:all
```

You can then pass one or more of the above entries to the runtime:
```shell
(cdi) root@ventunoq:~# docker run --network host --device qualcomm.com/gpu=renderD128 --device=qualcomm.com/fastrpc-cdsp=fastrpc-cdsp:all --rm -it aiml-container:latest /bin/bash
```
When using a CDI device, the container will automatically get additional metadata, for example the `MACHINE_NAME` environment variable:
```shell
(cdi) root@ventunoq:~# docker run --network host --device=qualcomm.com/fastrpc-cdsp=fastrpc-cdsp:all --rm -it aiml-container:latest /bin/bash
root@container:/# env | grep MACHINE
MACHINE_NAME=Arduino Monza
```

To generate only the fastrpc classes:
```shell
(cdi) root@ventunoq:~# qualcomm-cdi-generator --classes fastrpc-cdsp,fastrpc-adsp -v
INFO: Starting Qualcomm CDI generation
INFO: Config: destdir=/, hookfilename=vendorhook, cdifilename=qualcomm.json, dry_run=False
INFO: Found 1 nodes for pattern /dev/dri/renderD*
INFO: Generating CDI entries for 'renderD' with 1 node(s)
INFO: Found 30 nodes for pattern /dev/video*
INFO: Generating CDI entries for 'video' with 30 node(s)
INFO: Found 1 nodes for pattern /dev/dma_heap/*system
INFO: Generating CDI entries for 'dmaheap-system' with 1 node(s)
INFO: Found 2 nodes for pattern /dev/fastrpc-cdsp*
INFO: Generating CDI entries for 'fastrpc-cdsp' with 2 node(s)
INFO: Found 1 nodes for pattern /dev/fastrpc-adsp*
INFO: Generating CDI entries for 'fastrpc-adsp' with 1 node(s)
INFO: Total nodes aggregated for hook: 35
INFO: Detected Arduino Monza from devicetree
INFO: Found 14 nodes for pattern /usr/share/*/*/*/*/dsp/
INFO: Wrote hook script: /bin/vendorhook
INFO: Wrote CDI JSON: /run/cdi/qualcomm-fastrpc-cdsp.json
INFO: Wrote CDI JSON: /run/cdi/qualcomm-fastrpc-adsp.json
INFO: Completed Qualcomm CDI generation
```

### CDI file structure

The tool writes one JSON file per device class. Each file has a `kind` matching its class (e.g. `qualcomm.com/gpu`). The `fastrpc` files additionally include bind-mounts for Hexagon DSP firmware found under `/usr/share/*/*/*/*/dsp/` and the devicetree model string, since those binaries are tightly coupled to the in-kernel firmware loader.

Example `qualcomm-gpu.json`:
```json
{
  "cdiVersion": "0.6.0",
  "kind": "qualcomm.com/gpu",
  "devices": [
    {
      "name": "renderD128",
      "containerEdits": {
        "deviceNodes": [ { "path": "/dev/dri/renderD128" } ]
      }
    },
    {
      "name": "renderD:all",
      "containerEdits": {
        "deviceNodes": [ { "path": "/dev/dri/renderD128" } ]
      }
    }
  ],
  "containerEdits": {
    "hooks": [ { "hookname": "createContainer", "path": "/bin/vendorhook" } ],
    "env": [ "MACHINE_NAME=Qualcomm Technologies, Inc. Robotics RB3gen2" ]
  }
}
```

## Development

How to develop new features/fixes for the software. Maybe different than "usage". Also provide details on how to contribute via a [CONTRIBUTING.md file](CONTRIBUTING.md).

## Getting in Contact

How to contact maintainers. E.g. GitHub Issues, GitHub Discussions could be indicated for many cases. However a mail list or list of Maintainer e-mails could be shared for other types of discussions. E.g.

* [Report an Issue on GitHub](../../issues)

## License

*Qualcomm CDI generator* is licensed under the [BSD-3-clause License](https://spdx.org/licenses/BSD-3-Clause.html). See [LICENSE.txt](LICENSE.txt) for the full license text.
