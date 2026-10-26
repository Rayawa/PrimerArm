#!/usr/bin/env python3
"""Orange Pi AI Pro checks. No motion, torque, reset, or configuration commands."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def run(label, command):
    print(f'\n--- {label} ---', flush=True)
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                errors='replace', timeout=25)
        print(result.stdout.strip() or '(no stdout)')
        if result.stderr.strip():
            print(result.stderr.strip())
        print(f'exit_code={result.returncode}')
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f'CHECK FAILED: {error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/root/ros2_robot_arm'))
    parser.add_argument('--servo-status', action='store_true',
                        help='Read board version, servo status and angles; no motion.')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Run this script on the Orange Pi Linux board, not Windows.')

    print('Orange Pi arm preflight - NO MOTION / NO TORQUE CHANGES')
    print('Python:', sys.executable, platform.python_version())
    print('Machine:', platform.machine(), 'UID:', os.geteuid())
    print('ROS_DISTRO:', os.environ.get('ROS_DISTRO', '(not loaded)'))
    for rel in ['setenv.sh', 'ros2_ws/install/setup.bash',
                'ros2_ws/src/dofbot_moveit/urdf/dofbot.urdf']:
        path = args.root / rel
        print('EXISTS' if path.is_file() else 'MISSING', path)
    print('I2C node:', Path('/dev/i2c-7').exists())
    print('Camera nodes:', ', '.join(str(p) for p in sorted(Path('/dev').glob('video*'))) or 'NONE')
    print('Camera frame capture was not tested.')

    for name in ['smbus', 'Arm_Lib', 'numpy', 'cv2', 'torch', 'torchvision',
                 'rclpy', 'cv_bridge', 'ml_dtypes', 'acl', 'aclruntime',
                 'ais_bench.infer.interface']:
        code = ('import importlib; '
                f'm=importlib.import_module({name!r}); '
                'print("version:", getattr(m, "__version__", "n/a")); '
                'print("path:", getattr(m, "__file__", "n/a"))')
        if name == 'ais_bench.infer.interface':
            code += '; print("InferSession available:", hasattr(m, "InferSession"))'
        run('Import ' + name, [sys.executable, '-c', code])

    for pkg in ['dofbot_garbage_yolov5', 'robot_arm_color_stacking']:
        src = args.root / 'ros2_ws/src' / pkg / pkg
        installed = args.root / 'ros2_ws/install' / pkg / 'share' / pkg
        print(f'\n--- Files: {pkg} ---')
        for base in [src, installed]:
            for rel in ['model/yolov5s_bs1.om', 'model/coco_names.txt',
                        'config/XYT_config.txt', 'config/dp.bin', 'config/offset.txt']:
                path = base / rel
                print(f'{path.stat().st_size} bytes' if path.is_file() else 'MISSING', path)
        for path in sorted((src / 'utils').glob('*.py')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if line.startswith('CALIB_MODE =') or 'self.grap_joint =' in line:
                    print(f'{path.name}:{number}: {line.strip()}')
    print('Config presence does not prove calibration; model presence does not prove compatibility.')

    toolkit = Path('/usr/local/Ascend/ascend-toolkit')
    for path in [toolkit/'latest/aarch64-linux/ascend_toolkit_install.info', toolkit/'latest/version.cfg']:
        if path.is_file():
            print(f'\n--- CANN: {path} ---')
            print(path.read_text(encoding='utf-8', errors='replace')[:4000])
    if shutil.which('ros2'):
        run('Project package', ['ros2', 'pkg', 'prefix', 'dofbot_moveit'])
        run('ROS services', ['ros2', 'service', 'list'])
    else:
        print('ROS missing from PATH; source /opt/ros/humble/setup.bash first.')
    if shutil.which('npu-smi'):
        run('NPU status', ['npu-smi', 'info'])
        run('NPU health', ['npu-smi', 'info', '-t', 'health', '-i', '0'])
    else:
        print('npu-smi missing from PATH')

    if args.servo_status:
        run('Servo status READ ONLY', [sys.executable, '-c', '''
from Arm_Lib import Arm_Device
from time import sleep
arm = Arm_Device()
print('Board version:', arm.Arm_get_hardversion(), flush=True)
for joint in range(1, 7):
    try:
        status = arm.Arm_ping_servo(joint)
        sleep(0.1)
        angle = arm.Arm_serial_servo_read(joint)
        code = hex(status) if isinstance(status, int) else str(status)
        print(f'Joint {joint}: status={code}, angle={angle}', flush=True)
    except Exception as error:
        print(f'Joint {joint}: {type(error).__name__}: {error}', flush=True)
    sleep(0.1)
'''])
    print('\nFinished. No motion test or NPU model inference was performed.')


if __name__ == '__main__':
    main()
