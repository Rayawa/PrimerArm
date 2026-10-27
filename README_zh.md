# PrimerArm

[English](README.md) | 简体中文

包含 USB 手柄工具、ROS 2 集成与视觉示例的机械臂控制和诊断项目。

## 项目概述

仓库整理面向 DOFBOT 的控制、通信诊断、ROS 2 示例及昇腾开发板部署资料。根目录测试模拟硬件通信，命令行控制器默认不驱动硬件。

## 技术栈与依赖

根目录工具和测试使用 Python 3。实机操作需要 Linux、USB 手柄、Arm_Lib 驱动与可用 I²C。ROS 2、Ascend/CANN 依赖用于对应示例，不是离线测试的前提。

## 文件结构

- `gamepad_arm_control.py` — 控制器命令行
- `gamepad_preview.py` — 输入预览
- `arm_preflight.py` — 运行前检查
- `arm_feedback_diagnose.py` — 反馈诊断
- `robot_arm_dependency/` — 驱动与运动学资源
- `ros2_robot_arm/` — ROS 2 示例
- `doc/` — 操作和排障指南

## 快速上手

在仓库根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py'
python3 gamepad_arm_control.py --help
```

启用硬件控制前阅读[使用指南](doc/机械臂使用指南.md)，配置开发板、驱动和输入设备。测试使用所附驱动源码与模拟通信，通过测试不代表实机验收完成。
