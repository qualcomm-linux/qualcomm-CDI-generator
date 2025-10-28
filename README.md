# Project Name

*Qualcomm CDI generator*

Tooling to generate CDI config files to pass devices through to containers

## Branches

**main**: Primary development branch. Contributors should develop submissions based on this branch, and submit pull requests to this branch.

## Requirements

The main tool only requires python3 to generate a CDI. To consume it, you need a container runtime like podman or docker.

## Installation Instructions

Copy over `qualcomm-cdi-generator.py`

## Usage

On the target run the CDI generator:

```shell
# mkdir -p /run/cdi
# qualcomm-cdi-generator.py
```

Example session:
```shell
root@qcs6490-rb3gen2-core-kit:~# mkdir -p /run/cdi
root@qcs6490-rb3gen2-core-kit:~# ./qualcomm-cdi-generator.py
{'name': 'render0', 'containerEdits': {'deviceNodes': [{'path': '/dev/dri/renderD128'}]}}
{'name': 'video0', 'containerEdits': {'deviceNodes': [{'path': '/dev/video0'}]}}
{'name': 'video1', 'containerEdits': {'deviceNodes': [{'path': '/dev/video1'}]}}
root@qcs6490-rb3gen2-core-kit:~# docker info
[...]
Server:
 CDI spec directories:
  /etc/cdi
  /var/run/cdi
 Discovered Devices:
  cdi: qualcomm.com/gpu=render0
  cdi: qualcomm.com/gpu=render:all
  cdi: qualcomm.com/gpu=video0
  cdi: qualcomm.com/gpu=video1
  cdi: qualcomm.com/gpu=video:all
[...]
```
You can then pass one or more of the above entries to the runtime:
```
root@qcs6490-rb3gen2-core-kit:~# docker run --device qualcomm.com/gpu=render0 --device qualcomm.com/gpu=video:all [..]
```

## Development

How to develop new features/fixes for the software. Maybe different than "usage". Also provide details on how to contribute via a [CONTRIBUTING.md file](CONTRIBUTING.md).

## Getting in Contact

How to contact maintainers. E.g. GitHub Issues, GitHub Discussions could be indicated for many cases. However a mail list or list of Maintainer e-mails could be shared for other types of discussions. E.g.

* [Report an Issue on GitHub](../../issues)

## License

*Qualcomm CDI generator* is licensed under the [BSD-3-clause License](https://spdx.org/licenses/BSD-3-Clause.html). See [LICENSE.txt](LICENSE.txt) for the full license text.
