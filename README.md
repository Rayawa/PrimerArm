# PrimerArm

Robotic arm control and diagnostics with USB gamepad support, ROS 2 integration, and Ascend-based vision examples.

PrimerArm 整理了基于 DOFBOT 的机械臂控制工具、通信诊断、ROS 2 工程及使用资料，面向 Orange Pi AIpro / Atlas 200I DK A2 等昇腾开发环境。

## 项目内容

- **USB 手柄控制**：关节步进与持续控制、夹爪控制、输入预览及通信异常处理。
- **设备诊断**：运行前检查、舵机反馈与机械臂通信诊断。
- **ROS 2 工程**：配套运动控制、视觉抓取与积木堆叠示例及模型资源。
- **离线验证**：模拟硬件通信的 Python 测试，无需连接开发板。
- **配套资料**：操作指南、部署说明、故障核查记录和原始参考材料。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `gamepad_arm_control.py` | USB 手柄控制入口，默认不驱动硬件 |
| `gamepad_preview.py` | 手柄输入预览 |
| `arm_preflight.py` | 运行前检查 |
| `arm_feedback_diagnose.py` | 反馈与通信诊断 |
| `test_*.py` | 离线控制与通信测试 |
| `ros2_robot_arm/ros2_robot_arm/` | ROS 2 工程、配置、资源及上游说明 |
| `robot_arm_dependency/` | 配套驱动、运动学库和安装材料 |
| `doc/` | 操作指南和排查资料 |

根目录保留原始工程、依赖压缩包及机械臂实验文档，供追溯和部署参考。

## 快速开始

### 1. 获取项目

```bash
git clone https://github.com/Rayawa/PrimerArm.git
cd PrimerArm
```

### 2. 运行离线测试

在项目根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py'
```

测试直接读取本仓库 `robot_arm_dependency/0.py_install/Arm_Lib/Arm_Lib.py`，模拟设备通信，不需要连接机械臂。

### 3. 查看控制参数

```bash
python3 gamepad_arm_control.py --help
```

实际手柄读取和机械臂控制需要板端 Linux、USB 手柄、已安装的 `Arm_Lib` 驱动及可用的 I²C 连接。具体连接、操作和启停步骤见下方指南。

## 文档

- [机械臂使用指南](doc/机械臂使用指南.md)
- [USB 手柄控制说明](doc/USB手柄控制说明.md)
- [垃圾分类开机命令执行单](doc/垃圾分类开机命令执行单.md)
- [ROS 2 工程部署说明](ros2_robot_arm/ros2_robot_arm/README.md)
- [故障与核查记录](doc/故障与核查/)
- [排查原始材料](doc/排查原始材料/)

## 部署与验证状态

板端程序通过已安装的 `Arm_Lib` 使用驱动。将项目复制到板端后，仍需按配套教程安装 `robot_arm_dependency/0.py_install/` 中的驱动；本地目录移动不会自动更新板端安装。

ROS 2 示例依赖板端 ROS 2 Humble、CANN、ais_bench/aclruntime、相机标定和配套模型；工程内的 `requirements.txt` 未完整覆盖所有系统依赖。ARM64 安装材料应在对应板端使用。

当前仓库未包含视觉抓取和堆叠需要的 `yolov5s_bs1.om`，相关功能需补齐模型并在实物环境验证。离线测试通过只说明模拟场景符合预期，不能替代板端及实物验证。

## 来源与授权

仓库包含配套厂商工程、依赖和参考资料；第三方内容保留其原有授权说明。本仓库未额外授予统一的开源许可证。
