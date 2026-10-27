# PrimerArm

English | [简体中文](README_zh.md)

Robotic-arm control and diagnostics with USB gamepad tools, ROS 2 integration and vision examples.

## Overview

The repository collects DOFBOT-oriented controls, communication diagnostics, ROS 2 examples and deployment references for Ascend development boards. Root-level tests simulate hardware communication. The command-line controller defaults to a mode that does not drive the hardware.

## Technology and Dependencies

Python 3 for root tools and tests. Physical operation requires Linux, a USB gamepad, the Arm_Lib driver and a working I²C connection. ROS 2 and Ascend/CANN dependencies apply to the corresponding bundled examples rather than the offline tests.

## Repository Structure

- `gamepad_arm_control.py` — controller CLI
- `gamepad_preview.py` — input preview
- `arm_preflight.py` — preflight checks
- `arm_feedback_diagnose.py` — feedback diagnostics
- `robot_arm_dependency/` — driver and kinematics resources
- `ros2_robot_arm/` — ROS 2 examples
- `doc/` — operation and troubleshooting guides

## Quick Start

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py'
python3 gamepad_arm_control.py --help
```

Read the [operation guide](doc/机械臂使用指南.md) and configure the board, driver and input device before enabling hardware control. The tests use the included driver source with simulated transport; passing them does not verify a connected arm.
