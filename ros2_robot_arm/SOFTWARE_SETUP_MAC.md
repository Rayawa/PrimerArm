# Orange Pi AI Pro 机械臂垃圾分拣：Mac 端软件部署与运行手册

本文面向第一次接触 Linux、SSH、ROS 2 和昇腾推理的用户，目标是把 Mac 中已有的官方机械臂工程部署到 Orange Pi AI Pro，并运行 YOLOv5 垃圾识别与机械臂分拣程序。

本文只说明软件操作，不包含机械结构安装、供电、排线、摄像头固定等物理硬件步骤。

## 1. 最终要运行什么

项目由两个长期运行的 ROS 2 程序组成：

1. `dofbot_server`：机械臂正逆运动学服务。
2. `block_cls`：读取摄像头、调用昇腾 NPU 上的 YOLOv5 模型、计算目标位置并触发分拣动作。

最终需要在 Orange Pi 上分别运行：

```bash
ros2 run dofbot_moveit dofbot_server
```

```bash
ros2 run dofbot_garbage_yolov5 block_cls
```

官方工程在 Mac 上的位置：

```text
/Users/raychen/Develop/Ascend/OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm
```

你的个人仓库位置：

```text
/Users/raychen/Develop/Ascend/OrangePi/src/AIproRobotArm
```

机械臂依赖压缩包位置：

```text
/Users/raychen/Develop/Ascend/OrangePi/robot_arm_dependency.zip
```

> 重要：Mac 只用于保存代码、传文件和通过 SSH 操作开发板。ROS 2、Arm_Lib、昇腾推理环境和机械臂程序都安装、编译、运行在 Orange Pi 上。

## 2. 认识本手册中的终端

下面会使用两种终端，请先分清楚：

- **Mac 终端**：Mac 上的“终端”应用，提示符通常包含 Mac 用户名。
- **Orange Pi 终端**：通过 SSH 登录开发板后的终端，提示符通常包含 `orangepiaipro`、`HwHiAiUser` 或 `root`。

每个命令块前都会注明在哪一端执行。不要把 `apt`、ROS 2 安装命令在 Mac 上执行。

## 3. 从 Mac 登录 Orange Pi

### 3.1 打开 Mac 终端

按 `Command + 空格`，搜索“终端”并打开。

### 3.2 设置开发板 IP 变量

假设开发板 IP 是 `192.168.137.100`。在 **Mac 终端**执行：

```bash
BOARD_IP=192.168.137.100
```

如果开发板实际 IP 不同，将右侧地址替换成实际值。

### 3.3 测试网络

在 **Mac 终端**执行：

```bash
ping -c 4 "$BOARD_IP"
```

看到类似下面的内容表示网络可达：

```text
64 bytes from 192.168.137.100
```

如果全部超时，不要继续安装环境。先确认 Mac 和开发板的 IP 是否在同一网段，以及开发板当前 IP 是否正确。

### 3.4 SSH 登录

优先尝试开发板普通用户：

```bash
ssh HwHiAiUser@"$BOARD_IP"
```

如果镜像允许 root 直接登录，也可以使用：

```bash
ssh root@"$BOARD_IP"
```

首次连接会出现主机指纹确认：

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

输入：

```text
yes
```

然后输入开发板密码。输入密码时屏幕不会显示字符，这是正常现象。

如果使用 `HwHiAiUser` 登录，进入开发板后执行：

```bash
sudo -i
```

后续板端命令默认都在 root shell 中执行。可以用下面命令确认：

```bash
whoami
```

预期输出：

```text
root
```

## 4. 把工程和依赖从 Mac 传到开发板

先退出 SSH，回到 **Mac 终端**：

```bash
exit
```

### 4.1 传输主工程

在 **Mac 终端**执行：

```bash
scp -r "/Users/raychen/Develop/Ascend/OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm" \
  root@"$BOARD_IP":/root/
```

如果 root 不能直接 SSH，先传到普通用户目录：

```bash
scp -r "/Users/raychen/Develop/Ascend/OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm" \
  HwHiAiUser@"$BOARD_IP":/home/HwHiAiUser/
```

然后 SSH 登录开发板并执行：

```bash
sudo -i
cp -a /home/HwHiAiUser/ros2_robot_arm /root/
```

### 4.2 传输机械臂依赖包

在 **Mac 终端**执行：

```bash
scp "/Users/raychen/Develop/Ascend/OrangePi/robot_arm_dependency.zip" \
  root@"$BOARD_IP":/root/ros2_robot_arm/
```

如果只能使用普通用户：

```bash
scp "/Users/raychen/Develop/Ascend/OrangePi/robot_arm_dependency.zip" \
  HwHiAiUser@"$BOARD_IP":/home/HwHiAiUser/
```

登录开发板后执行：

```bash
sudo -i
cp /home/HwHiAiUser/robot_arm_dependency.zip /root/ros2_robot_arm/
```

### 4.3 验证文件是否完整

在 **Orange Pi 终端**执行：

```bash
cd /root/ros2_robot_arm
pwd
ls
```

至少应看到：

```text
README.md
requirements.txt
ros2_ws
setenv.sh
robot_arm_dependency.zip
```

解压依赖：

```bash
cd /root/ros2_robot_arm
unzip -o robot_arm_dependency.zip
```

解压后还应看到：

```text
0.py_install
orocos_kdl
libdofbot_kinemarics.so
libconsole-bridge0.4_0.4.4+dfsg-1build1_arm64.deb
liburdfdom-world_1.0.0-2ubuntu0.1_arm64.deb
```

## 5. 记录系统基线

在安装任何东西前，在 **Orange Pi 终端**依次执行：

```bash
uname -m
lsb_release -a
python3 --version
pip3 --version
```

预期重点：

- CPU 架构应是 `aarch64`。
- 系统应是 Ubuntu 22.04，才能直接使用 ROS 2 Humble。
- 官方依赖包内包含 Python 3.10 生成的内容，因此 Python 3.10 最匹配。

检查昇腾设备与工具链：

```bash
npu-smi info
ls /usr/local/Ascend
```

尝试加载昇腾环境：

```bash
if [ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
elif [ -f /usr/local/Ascend/ascend-toolkit/latest/set_env.sh ]; then
  source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh
fi
```

再次执行：

```bash
npu-smi info
```

如果 `npu-smi` 不存在或报找不到设备，不要继续折腾 ROS 2；应先恢复开发板镜像自带的 CANN/NPU 驱动环境。此项目依赖昇腾运行时，不能只安装普通 Python 包代替。

## 6. 禁止开发板自动休眠

在 **Orange Pi 终端**执行：

```bash
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

这可以避免长时间安装、编译或运行时 SSH 因系统休眠而断开。

## 7. 安装 ROS 2 Humble

以下命令均在 **Orange Pi 终端**执行。

### 7.1 安装基础工具

```bash
apt update
apt install -y software-properties-common curl gnupg lsb-release
```

### 7.2 添加 ROS 2 软件源

下载 ROS 2 软件源签名：

```bash
curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
```

如果访问 GitHub 很慢，可以稍后重试；签名文件没有成功下载时不要继续执行安装。

添加 Ubuntu 22.04 对应的软件源：

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  > /etc/apt/sources.list.d/ros2.list
```

更新软件索引：

```bash
apt update
```

### 7.3 安装 ROS 2 与项目编译依赖

```bash
apt install -y \
  ros-humble-desktop \
  ros-humble-joint-state-publisher-gui \
  ros-humble-xacro \
  python3-colcon-common-extensions \
  python3-pip \
  build-essential \
  cmake \
  libegl-mesa0 \
  libopencv-dev \
  libboost-all-dev
```

加载 ROS 2：

```bash
source /opt/ros/humble/setup.bash
```

验证：

```bash
echo "$ROS_DISTRO"
which ros2
```

预期输出分别包含：

```text
humble
/opt/ros/humble/bin/ros2
```

### 7.4 测试 ROS 2 自身是否正常

打开两个 SSH 窗口。

第一个 **Orange Pi 终端**执行：

```bash
source /opt/ros/humble/setup.bash
ros2 run demo_nodes_cpp talker
```

第二个 **Orange Pi 终端**执行：

```bash
source /opt/ros/humble/setup.bash
ros2 run demo_nodes_py listener
```

如果 listener 持续收到 `Hello World`，ROS 2 通信正常。分别按 `Control + C` 停止。

## 8. 安装 Python 依赖

项目要求使用系统 Python，不要在 Conda 环境内安装。

检查当前是否处于 Conda 环境：

```bash
echo "$CONDA_DEFAULT_ENV"
```

如果输出 `base` 或其他环境名，执行：

```bash
conda deactivate
```

进入项目：

```bash
cd /root/ros2_robot_arm
```

先更新基础打包工具：

```bash
python3 -m pip install --upgrade pip setuptools wheel
```

安装项目 Python 依赖：

```bash
python3 -m pip install -r requirements.txt \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

项目固定了旧版 `torch==1.13.0`、`torchvision==0.14.0`、`numpy==1.22.4` 等依赖。不要擅自升级到最新版，否则 YOLOv5 后处理和 ROS 2 Python 环境可能不兼容。

安装 `ais_bench` 及昇腾推理后端：

```bash
python3 -m pip install -v \
  'git+https://gitee.com/ascend/tools.git#egg=aclruntime&subdirectory=ais-bench_workload/tool/ais_bench/backend' \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

```bash
python3 -m pip install -v \
  'git+https://gitee.com/ascend/tools.git#egg=ais_bench&subdirectory=ais-bench_workload/tool/ais_bench' \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

验证关键 Python 模块：

```bash
python3 - <<'PY'
import cv2
import numpy
import torch
import torchvision
from ais_bench.infer.interface import InferSession

print("OpenCV:", cv2.__version__)
print("NumPy:", numpy.__version__)
print("PyTorch:", torch.__version__)
print("TorchVision:", torchvision.__version__)
print("ais_bench import: OK")
PY
```

## 9. 安装机械臂软件依赖

以下命令均在 **Orange Pi 终端**执行。

### 9.1 安装 ARM64 二进制包

```bash
cd /root/ros2_robot_arm
dpkg -i libconsole-bridge0.4_0.4.4+dfsg-1build1_arm64.deb
dpkg -i liburdfdom-world_1.0.0-2ubuntu0.1_arm64.deb
```

如果 `dpkg` 提示缺少依赖，执行：

```bash
apt --fix-broken install -y
```

然后重新执行上面的两条 `dpkg -i` 命令。

### 9.2 安装机械臂运动学动态库

```bash
cd /root/ros2_robot_arm
install -m 0644 libdofbot_kinemarics.so /usr/lib/libdofbot_kinemarics.so
ldconfig
```

验证：

```bash
ldconfig -p | grep dofbot
```

### 9.3 编译并安装 Orocos KDL

```bash
cd /root/ros2_robot_arm/orocos_kdl
mkdir -p build
cd build
cmake ..
make -j"$(nproc)"
make install
ldconfig
```

### 9.4 安装 Arm_Lib Python 驱动

```bash
cd /root/ros2_robot_arm/0.py_install
python3 setup.py install
```

只验证能否导入，不要在此时发送运动命令：

```bash
python3 - <<'PY'
import Arm_Lib
print("Arm_Lib import: OK")
print("Arm_Device class:", Arm_Lib.Arm_Device)
PY
```

## 10. 准备 YOLOv5 OM 模型

当前 Mac 工程中有标签文件，但没有 `yolov5s_bs1.om`。缺少模型时，程序会在创建 `InferSession` 阶段失败。

在 **Orange Pi 终端**下载：

```bash
MODEL_URL=https://eduhicomputing.obs.cn-south-1.myhuaweicloud.com/document/robot/yolov5s_bs1.om
GARBAGE_MODEL_DIR=/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/model
STACKING_MODEL_DIR=/root/ros2_robot_arm/ros2_ws/src/robot_arm_color_stacking/robot_arm_color_stacking/model

wget -O "$GARBAGE_MODEL_DIR/yolov5s_bs1.om" "$MODEL_URL"
cp "$GARBAGE_MODEL_DIR/yolov5s_bs1.om" "$STACKING_MODEL_DIR/yolov5s_bs1.om"
```

检查文件必须存在且大小不能为 0：

```bash
ls -lh "$GARBAGE_MODEL_DIR/yolov5s_bs1.om"
ls -lh "$STACKING_MODEL_DIR/yolov5s_bs1.om"
test -s "$GARBAGE_MODEL_DIR/yolov5s_bs1.om" && echo "garbage model: OK"
test -s "$STACKING_MODEL_DIR/yolov5s_bs1.om" && echo "stacking model: OK"
```

项目当前的 `coco_names.txt` 只有三行：

```text
Fish_bone
Newspaper
Syringe
```

因此这份示例模型主要识别鱼骨、报纸和注射器三个演示类别。不要用普通 COCO YOLOv5 模型替代；类别、输出结构和后处理必须匹配当前代码。

## 11. 设置运行环境

项目已有 `/root/ros2_robot_arm/setenv.sh`，内容会：

- 退出 Conda 环境；
- 加载 ROS 2 Humble；
- 加载当前 ROS 2 工作空间；
- 添加动态库搜索路径。

首次编译前执行：

```bash
cd /root/ros2_robot_arm
source setenv.sh
```

首次执行时可能出现：

```text
./ros2_ws/install/setup.bash: No such file or directory
```

这是因为工作空间尚未编译，可以暂时忽略。

如果 `conda deactivate` 提示命令不存在，但当前也不在 Conda 环境中，同样可以忽略。

## 12. 编译 ROS 2 工作空间

在 **Orange Pi 终端**执行：

```bash
cd /root/ros2_robot_arm
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --symlink-install
```

编译成功后执行：

```bash
source /root/ros2_robot_arm/ros2_ws/install/setup.bash
```

检查五个项目包：

```bash
ros2 pkg list | grep -E 'dofbot|robot_arm'
```

预期至少看到：

```text
dofbot_garbage_yolov5
dofbot_info
dofbot_moveit
robot_arm_bringup
robot_arm_color_stacking
```

检查可执行程序：

```bash
ros2 pkg executables dofbot_moveit
ros2 pkg executables dofbot_garbage_yolov5
```

预期包含：

```text
dofbot_moveit dofbot_server
dofbot_garbage_yolov5 block_cls
```

## 13. 首次软件校准

校准的作用是生成当前摄像头画面到机械臂坐标系的映射数据。工程里虽然已有 `dp.bin`、`XYT_config.txt` 和 `offset.txt`，但它们来自其他设备，不能保证适合当前设备。

### 13.1 打开校准模式

编辑以下两个文件：

```text
/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/utils/garbage_identify.py
/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/utils/npu_utils.py
```

把两个文件中的：

```python
CALIB_MODE = False
```

临时改为：

```python
CALIB_MODE = True
```

初学者可使用 `nano`：

```bash
nano /root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/utils/garbage_identify.py
```

保存方法：按 `Control + O`，回车确认，再按 `Control + X` 退出。另一个文件同样修改。

### 13.2 启动 Jupyter

确认没有其他程序正在占用摄像头，然后执行：

```bash
cd /root/ros2_robot_arm
source setenv.sh
jupyter notebook --allow-root --ip 0.0.0.0 --no-browser
```

终端会显示带 token 的地址。假设开发板 IP 是 `192.168.137.100`，在 Mac 浏览器打开：

```text
http://192.168.137.100:8888
```

如果要求 token，将 Orange Pi 终端输出中 `token=` 后面的内容复制到浏览器。

在网页中打开：

```text
ros2_ws/src/dofbot_garbage_yolov5/tools/相机校准.ipynb
```

选择 `Kernel` → `Restart & Run All`。如果第一次没有显示交互界面，再执行一次 `Restart & Run All`。

完成校准后，在 Orange Pi 终端按 `Control + C` 停止 Jupyter。不要让 Jupyter 与正式程序同时占用摄像头。

### 13.3 关闭校准模式

把两个文件中的：

```python
CALIB_MODE = True
```

改回：

```python
CALIB_MODE = False
```

### 13.4 将校准数据同步到堆叠程序

```bash
GARBAGE_CONFIG=/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/config
STACKING_CONFIG=/root/ros2_robot_arm/ros2_ws/src/robot_arm_color_stacking/robot_arm_color_stacking/config

cp "$GARBAGE_CONFIG/XYT_config.txt" "$STACKING_CONFIG/XYT_config.txt"
cp "$GARBAGE_CONFIG/dp.bin" "$STACKING_CONFIG/dp.bin"
cp "$GARBAGE_CONFIG/offset.txt" "$STACKING_CONFIG/offset.txt"
```

### 13.5 重新编译

```bash
cd /root/ros2_robot_arm/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

## 14. 正式启动垃圾分拣程序

为了便于定位问题，第一次运行建议使用两个 SSH 窗口，而不是一键 launch。

### 14.1 终端 1：启动运动学服务

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 run dofbot_moveit dofbot_server
```

保持该终端运行，不要关闭。

### 14.2 终端 2：确认服务存在

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 service list | grep trial_service
```

预期看到：

```text
/trial_service
```

### 14.3 终端 2：启动识别与分拣

```bash
ros2 run dofbot_garbage_yolov5 block_cls
```

程序启动后应经历以下阶段：

1. 加载 `yolov5s_bs1.om`。
2. 读取 `XYT_config.txt`、`dp.bin` 和 `offset.txt`。
3. 初始化 `Arm_Lib`。
4. 打开摄像头索引 0。
5. 模型预热。
6. 识别连续稳定后调用 `/trial_service` 计算关节角。
7. 调用机械臂控制接口执行分类动作。

使用 `Control + C` 停止程序。

### 14.4 后续可使用一键启动

确认两个程序分别运行正常后，可以使用：

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 launch robot_arm_bringup block_cls_bringup.launch.py
```

## 15. 可选：运行积木堆叠程序

终端 1：

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 run dofbot_moveit dofbot_server
```

终端 2：

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 run robot_arm_color_stacking color_stacking
```

一键启动方式：

```bash
ros2 launch robot_arm_bringup color_stacking_bringup.launch.py
```

## 16. 调整软件补偿参数

垃圾分拣补偿文件：

```text
/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/config/offset.txt
```

文件有两行浮点数：

```text
0.016
0.01
```

- 第一行：Y 轴，即前后方向补偿。
- 第二行：X 轴，即左右方向补偿。

建议每次只修改 `0.002`：

- 抓取位置偏后：适当增大 Y。
- 抓取位置偏前：适当减小 Y。
- 左右偏差：用同样的小步长修改 X。

修改后重新编译：

```bash
cd /root/ros2_robot_arm/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

夹爪闭合量位于：

```text
/root/ros2_robot_arm/ros2_ws/src/dofbot_garbage_yolov5/dofbot_garbage_yolov5/utils/garbage_grap.py
```

对应变量：

```python
self.grap_joint = 120
```

不要盲目提高该值。原实验手册明确提示超过 120 可能夹得过紧。

## 17. 每次重启开发板后的运行步骤

系统环境和项目都安装好以后，每次重启只需：

终端 1：

```bash
ssh root@192.168.137.100
cd /root/ros2_robot_arm
source setenv.sh
ros2 run dofbot_moveit dofbot_server
```

终端 2：

```bash
ssh root@192.168.137.100
cd /root/ros2_robot_arm
source setenv.sh
ros2 run dofbot_garbage_yolov5 block_cls
```

不需要每次重装依赖、重新编译或重新校准。只有代码、模型或配置文件改变后才需要重新 `colcon build`。

## 18. 常见错误与处理方法

### 18.1 `ssh: connect to host ... port 22: Operation timed out`

含义：Mac 无法访问开发板。

检查：

```bash
ping -c 4 192.168.137.100
```

还要确认开发板 SSH 服务：

```bash
systemctl status ssh
```

必要时在板端启动：

```bash
systemctl enable --now ssh
```

### 18.2 `ros2: command not found`

执行：

```bash
source /opt/ros/humble/setup.bash
```

### 18.3 `Package 'dofbot_...' not found`

执行：

```bash
cd /root/ros2_robot_arm/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

### 18.4 `No module named Arm_Lib`

重新安装：

```bash
cd /root/ros2_robot_arm/0.py_install
python3 setup.py install
python3 -c 'import Arm_Lib; print(Arm_Lib.__file__)'
```

### 18.5 `No module named ais_bench` 或 `aclruntime`

说明推理工具没有装到当前 Python。检查：

```bash
which python3
python3 -m pip --version
python3 -m pip show ais-bench aclruntime
```

确保没有进入 Conda，然后重新执行第 8 节的两条安装命令。

### 18.6 找不到 `yolov5s_bs1.om`

检查源目录：

```bash
find /root/ros2_robot_arm/ros2_ws/src -name yolov5s_bs1.om -ls
```

检查编译安装目录：

```bash
find /root/ros2_robot_arm/ros2_ws/install -name yolov5s_bs1.om -ls
```

源目录没有模型时，回到第 10 节下载。源目录有而安装目录没有时，重新 `colcon build --symlink-install`。

### 18.7 `failed to open camera` 或循环没有图像

查找占用摄像头的进程：

```bash
fuser /dev/video0
```

特别检查 Jupyter 是否仍在运行：

```bash
ps aux | grep -E 'jupyter|block_cls' | grep -v grep
```

先正常停止旧程序，再重新启动。不要让校准 Notebook 和 `block_cls` 同时运行。

### 18.8 `/trial_service` 不存在

说明运动学服务没有成功启动。先单独运行：

```bash
cd /root/ros2_robot_arm
source setenv.sh
ros2 run dofbot_moveit dofbot_server
```

重点查看是否提示找不到 `libdofbot_kinemarics.so`。如果是，执行：

```bash
install -m 0644 /root/ros2_robot_arm/libdofbot_kinemarics.so /usr/lib/libdofbot_kinemarics.so
ldconfig
```

### 18.9 `colcon build` 失败

不要只截取最后一行。重新编译并保存完整日志：

```bash
cd /root/ros2_robot_arm/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --event-handlers console_direct+ 2>&1 | tee /root/robot_arm_colcon.log
```

然后查看第一个真正的错误：

```bash
grep -n -i -E 'error:|failed|not found' /root/robot_arm_colcon.log | head -n 30
```

### 18.10 NPU 模型加载失败

依次检查：

```bash
npu-smi info
python3 -c 'from ais_bench.infer.interface import InferSession; print("import OK")'
find /root/ros2_robot_arm -name yolov5s_bs1.om -ls
```

如果模型存在、Python 能导入，但 `InferSession` 仍无法加载，通常是 OM 模型与当前芯片/CANN 版本不兼容。此时需要使用文档指定的模型，或针对当前 Orange Pi AI Pro 芯片重新转换模型，不能通过修改文件名解决。

## 19. 跑通判定清单

按顺序确认：

- [ ] Mac 可以通过 SSH 登录 Orange Pi。
- [ ] `/root/ros2_robot_arm` 包含源码、依赖目录和动态库。
- [ ] `uname -m` 输出 `aarch64`。
- [ ] `npu-smi info` 正常显示 NPU。
- [ ] `echo $ROS_DISTRO` 输出 `humble`。
- [ ] ROS 2 talker/listener 测试通过。
- [ ] `import Arm_Lib` 成功。
- [ ] `import InferSession` 成功。
- [ ] 两个模型目录都有非空的 `yolov5s_bs1.om`。
- [ ] `colcon build` 无失败包。
- [ ] `ros2 pkg list` 能找到五个机械臂包。
- [ ] `dofbot_server` 启动后能看到 `/trial_service`。
- [ ] 首次软件校准已完成，`CALIB_MODE` 已恢复为 `False`。
- [ ] `block_cls` 能打开摄像头并完成模型预热。
- [ ] 程序能识别 `Fish_bone`、`Newspaper` 或 `Syringe`。
- [ ] 必要时已小步调整 `offset.txt`。

## 20. 建议的排错顺序

出现问题时始终按下面顺序排查，不要一次修改很多东西：

1. SSH 和网络是否正常。
2. NPU/CANN 是否正常。
3. ROS 2 自身是否正常。
4. Python 依赖能否逐项导入。
5. 动态库能否被系统找到。
6. OM 模型是否存在且与平台兼容。
7. ROS 2 工作空间是否成功编译并加载。
8. `dofbot_server` 是否提供 `/trial_service`。
9. `block_cls` 是否能打开摄像头并完成推理。
10. 最后才调整校准和补偿参数。

这样能把“环境问题”“编译问题”“推理问题”和“标定问题”分开，不会在一个错误尚未解决时引入新的变量。

## 21. 主要本地参考资料

- 官方工程：`/Users/raychen/Develop/Ascend/OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm`
- 项目 README：`/Users/raychen/Develop/Ascend/OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm/README.md`
- 实验手册：`/Users/raychen/Develop/Ascend/OrangePi/doc/项目/香橙派AIpro机械臂垃圾分类实验4.7.docx`
- 环境文档：`/Users/raychen/Develop/Ascend/OrangePi/doc/环境/手把手教你搭建Orange Pi AI Pro开发环境.docx`
- 机械臂依赖：`/Users/raychen/Develop/Ascend/OrangePi/robot_arm_dependency.zip`

