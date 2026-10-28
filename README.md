# PrimerArm

English | [简体中文](README_zh.md)


Robotic arm control and diagnostics with USB gamepad support, ROS 2 integration, and Ascend-based vision examples.

PrimerArm collects DOFBOT-based arm-control tools, communication diagnostics, ROS 2 projects and documentation for Ascend development environments such as Orange Pi AIpro and Atlas 200I DK A2.

## Project Contents

- **USB gamepad control**: joint steps and continuous motion, gripper control, input preview and communication-error handling.
- **Device diagnostics**: preflight checks, servo feedback and arm-communication diagnostics.
- **ROS 2 projects**: motion control, visual grasping, block-stacking examples and model resources.
- **Offline verification**: Python tests with simulated hardware communication, without a connected board.
- **Supporting material**: operation guides, deployment instructions, troubleshooting records and original references.

## Repository Structure

| Path | Contents |
| --- | --- |
| `gamepad_arm_control.py` | USB gamepad entry point; does not drive hardware by default |
| `gamepad_preview.py` | Gamepad input preview |
| `arm_preflight.py` | Preflight checks |
| `arm_feedback_diagnose.py` | Feedback and communication diagnostics |
| `test_*.py` | Offline control and communication tests |
| `ros2_robot_arm/ros2_robot_arm/` | ROS 2 project, configuration, resources and upstream notes |
| `robot_arm_dependency/` | Drivers, kinematics libraries and installation material |
| `doc/` | Operation and troubleshooting guides |

The root retains the original project, dependency archives and arm-experiment documents for traceability and deployment reference.

## Quick Start

### 1. Obtain the Project

```bash
git clone https://github.com/Rayawa/PrimerArm.git
cd PrimerArm
```

### 2. Run Offline Tests

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py'
```

The tests load `robot_arm_dependency/0.py_install/Arm_Lib/Arm_Lib.py` from this repository and simulate device communication; no arm connection is required.

### 3. Inspect Control Options

```bash
python3 gamepad_arm_control.py --help
```

Actual gamepad input and arm control require board-side Linux, a USB gamepad, the installed `Arm_Lib` driver and a working I²C connection. See the guides below for wiring, operation, startup and shutdown procedures.

## Documentation

- [Arm operation guide](doc/机械臂使用指南.md)
- [USB gamepad controls](doc/USB手柄控制说明.md)
- [Waste-sorting startup command sheet](doc/垃圾分类开机命令执行单.md)
- [ROS 2 deployment guide](ros2_robot_arm/ros2_robot_arm/README.md)
- [Faults and verification records](doc/故障与核查/)
- [Original troubleshooting material](doc/排查原始材料/)

## Deployment and Verification Status

Board-side programs use the installed `Arm_Lib` driver. After copying the project to a board, install the driver from `robot_arm_dependency/0.py_install/` following its guide; moving the local directory does not update the installed board-side copy.

The ROS 2 examples require ROS 2 Humble, CANN, ais_bench/aclruntime, camera calibration and matching models on the board. The included `requirements.txt` does not cover every system dependency. Use ARM64 installation material on the corresponding board.

The repository does not currently include `yolov5s_bs1.om`, which is required for visual grasping and stacking. Supply the model and verify these functions on physical hardware. Passing offline tests only verifies the simulated scenarios and does not replace board-side or physical validation.

## Sources and Licensing

The repository includes vendor projects, dependencies and references, retaining their original licensing notices. No additional repository-wide open-source license is granted.
